import logging
import functions_framework
import os
import argparse
import requests
import subprocess
import threading
import time
import contextlib


from utils import ok

@functions_framework.http
def handle_job_request(request):
    job = request.get_json()
    if not job:
        logging.error("Invalid job data received")
        return "Invalid job data", 400

    try:
        args = get_args()
        engine = Engine(args)
        handle_job(args, engine, job)
        return "Job processed successfully", 200
    except Exception as e:
        logging.error("Failed to process job: %s", e)
        return "Failed to process job", 500


def get_args():
    parser = argparse.ArgumentParser(description='Engine Arguments')
    parser.add_argument('--engine', default=os.environ.get('ENGINE_COMMAND'))
    parser.add_argument('--setoption', nargs='*', default=[])
    parser.add_argument('--token', default=os.environ.get('LICHESS_API_TOKEN'))
    parser.add_argument('--max_threads', type=int, default=int(os.environ.get('MAX_THREADS', os.cpu_count())))
    parser.add_argument('--max_hash', type=int, default=int(os.environ.get('MAX_HASH', '512')))
    parser.add_argument('--keep_alive', type=int, default=int(os.environ.get('KEEP_ALIVE', '300')))
    parser.add_argument('--log_level', default=os.environ.get('LOG_LEVEL', 'info'))

    args = parser.parse_args()

    if not args.engine:
        logging.error("ENGINE_COMMAND environment variable is required")
        exit(1)

    if not args.token:
        logging.error("LICHESS_API_TOKEN environment variable is required")
        exit(1)

    return args

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