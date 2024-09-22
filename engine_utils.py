import logging
import requests
import os
import secrets
import subprocess
import threading
import time
import contextlib

_LOG_LEVEL_MAP = {
    "critical": logging.CRITICAL,
    "error": logging.ERROR,
    "warning": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
    "notset": logging.NOTSET,
}

def get_args():
    class Args:
        pass

    args = Args()
    args.name = os.environ.get('ENGINE_NAME', 'Alpha 2')
    args.engine = os.environ.get('ENGINE_COMMAND')
    if not args.engine:
        logging.error("ENGINE_COMMAND environment variable is required")
        raise ValueError("ENGINE_COMMAND environment variable is required")

    args.setoption = []  # Add custom UCI options if needed, e.g., [('Hash', '1024')]
    args.lichess = os.environ.get('LICHESS_URL', 'https://lichess.org')
    args.broker = os.environ.get('BROKER_URL', 'https://engine.lichess.ovh')
    args.token = os.environ.get('LICHESS_API_TOKEN')
    if not args.token:
        logging.error("LICHESS_API_TOKEN environment variable is required")
        raise ValueError("LICHESS_API_TOKEN environment variable is required")

    args.provider_secret = os.environ.get('PROVIDER_SECRET')
    args.max_threads = int(os.environ.get('MAX_THREADS', os.cpu_count()))
    args.max_hash = int(os.environ.get('MAX_HASH', '512'))
    args.keep_alive = int(os.environ.get('KEEP_ALIVE', '300'))
    args.log_level = os.environ.get('LOG_LEVEL', 'info')
    args.cloud_function_url = os.environ.get('CLOUD_FUNCTION_URL')
    args.poll_interval = int(os.environ.get('POLL_INTERVAL', '10'))
    
    logging.getLogger().setLevel(_LOG_LEVEL_MAP.get(args.log_level.lower(), logging.INFO))
    
    return args

def setup_http_session(token):
    http = requests.Session()
    http.headers["Authorization"] = f"Bearer {token}"
    return http

def ok(res):
    try:
        res.raise_for_status()
    except requests.exceptions.HTTPError:
        logging.error("Response: %s", res.text)
        raise
    return res

def register_engine(args, http):
    res = ok(http.get(f"{args.lichess}/api/external-engine"))

    secret = args.provider_secret or secrets.token_urlsafe(32)

    variants = {
        "chess",
        "antichess",
        "atomic",
        "crazyhouse",
        "horde",
        "kingofthehill",
        "racingkings",
        "3check",
    }

    # Engine instance is needed to get supported variants
    engine = Engine(args)
    supported_variants = engine.supported_variants or ["chess"]
    engine.terminate()  # Terminate the engine after getting supported variants

    registration = {
        "name": args.name,
        "maxThreads": args.max_threads,
        "maxHash": args.max_hash,
        "variants": [variant for variant in supported_variants if variant in variants],
        "providerSecret": secret,
    }

    for engine_data in res.json():
        if engine_data["name"] == args.name:
            logging.info("Updating engine %s", engine_data["id"])
            ok(http.put(f"{args.lichess}/api/external-engine/{engine_data['id']}", json=registration))
            break
    else:
        logging.info("Registering new engine")
        ok(http.post(f"{args.lichess}/api/external-engine", json=registration))

    return secret

def invoke_cloud_function(cloud_function_url, job):
    try:
        res = requests.post(cloud_function_url, json=job)
        res.raise_for_status()
        logging.info("Cloud function invoked successfully")
    except requests.exceptions.RequestException as err:
        logging.error("Error invoking cloud function: %s", err)

def handle_job(args, engine, job):
    try:
        logging.info("Handling job %s", job["id"])
        with engine.analyse(job) as analysis_stream:
            ok(requests.post(
                f"{args.broker}/api/external-engine/work/{job['id']}",
                data=analysis_stream
            ))
    except requests.exceptions.ConnectionError:
        logging.info("Connection closed while streaming analysis")
    except requests.exceptions.RequestException as err:
        logging.error("Error while submitting work: %s", err)
    except EOFError:
        logging.error("Engine died")

class Engine:
    def __init__(self, args):
        self.process = subprocess.Popen(
            args.engine,
            shell=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            bufsize=1,
            universal_newlines=True
        )
        self.args = args
        self.session_id = None
        self.hash = None
        self.threads = None
        self.multi_pv = None
        self.uci_variant = None
        self.supported_variants = []
        self.last_used = time.monotonic()
        self.alive = True
        self.stop_lock = threading.Lock()

        self.uci()
        self.setoption("UCI_AnalyseMode", "true")
        self.setoption("UCI_Chess960", "true")
        for name, value in args.setoption:
            self.setoption(name, value)

    def idle_time(self):
        return time.monotonic() - self.last_used

    def terminate(self):
        self.process.terminate()
        self.alive = False

    def send(self, command):
        logging.debug("%d << %s", self.process.pid, command)
        self.process.stdin.write(command + "\n")
        self.process.stdin.flush()

    def recv(self):
        while True:
            line = self.process.stdout.readline()
            if line == "":
                self.alive = False
                raise EOFError()

            line = line.rstrip()
            if not line:
                continue

            logging.debug("%d >> %s", self.process.pid, line)

            command_and_params = line.split(None, 1)

            if len(command_and_params) == 1:
                return command_and_params[0], ""
            else:
                return command_and_params

    def uci(self):
        self.send("uci")
        while True:
            command, args = self.recv()
            if command == "option":
                name = None
                args = args.split()
                while args:
                    arg = args.pop(0)
                    if arg == "name":
                        name = args.pop(0)
                    elif name == "UCI_Variant" and arg == "var":
                        self.supported_variants.append(args.pop(0))
            elif command == "uciok":
                break

        if self.supported_variants:
            logging.info("Supported variants: %s", ", ".join(self.supported_variants))

    def isready(self):
        self.send("isready")
        while True:
            line, _ = self.recv()
            if line == "readyok":
                break

    def setoption(self, name, value):
        self.send(f"setoption name {name} value {value}")

    @contextlib.contextmanager
    def analyse(self, job):
        work = job["work"]

        if work["sessionId"] != self.session_id:
            self.session_id = work["sessionId"]
            self.send("ucinewgame")
            self.isready()

        options_changed = False
        if self.threads != work["threads"]:
            self.setoption("Threads", work["threads"])
            self.threads = work["threads"]
            options_changed = True
        if self.hash != work["hash"]:
            self.setoption("Hash", work["hash"])
            self.hash = work["hash"]
            options_changed = True
        if self.multi_pv != work["multiPv"]:
            self.setoption("MultiPV", work["multiPv"])
            self.multi_pv = work["multiPv"]
            options_changed = True
        if self.uci_variant != work["variant"]:
            self.setoption("UCI_Variant", work["variant"])
            self.uci_variant = work["variant"]
            options_changed = True
        if options_changed:
            self.isready()

        self.send(f"position fen {work['initialFen']} moves {' '.join(work['moves'])}")

        go_options = ""
        for key in ["movetime", "depth", "nodes"]:
            if key in work:
                go_options += f" {key} {work[key]}"
                break  # Only one time control is used

        self.send(f"go{go_options}")

        def stream():
            while True:
                command, params = self.recv()
                if command == "bestmove":
                    break
                elif command == "info":
                    if "score" in params:
                        yield (command + " " + params + "\n").encode("utf-8")
                else:
                    logging.warning("Unexpected engine command: %s", command)

        analysis = stream()
        try:
            yield analysis
        finally:
            self.stop()
            for _ in analysis:
                pass

        self.last_used = time.monotonic()

    def stop(self):
        if self.alive:
            with self.stop_lock:
                self.send("stop")