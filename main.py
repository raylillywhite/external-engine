import logging
import requests
import time
import threading
import os
import secrets
import argparse
from utils import ok, setup_http_session

def get_args():
    parser = argparse.ArgumentParser(description='Engine Arguments')
    parser.add_argument('--name', default=os.environ.get('ENGINE_NAME', 'Alpha 2'))
    parser.add_argument('--engine', default=os.environ.get('ENGINE_COMMAND'))
    parser.add_argument('--setoption', nargs='*', default=[])
    parser.add_argument('--lichess', default=os.environ.get('LICHESS_URL', 'https://lichess.org'))
    parser.add_argument('--broker', default=os.environ.get('BROKER_URL', 'https://engine.lichess.ovh'))
    parser.add_argument('--token', default=os.environ.get('LICHESS_API_TOKEN'))
    parser.add_argument('--max_threads', type=int, default=int(os.environ.get('MAX_THREADS', os.cpu_count())))
    parser.add_argument('--max_hash', type=int, default=int(os.environ.get('MAX_HASH', '512')))
    parser.add_argument('--keep_alive', type=int, default=int(os.environ.get('KEEP_ALIVE', '300')))
    parser.add_argument('--poll_timeout', type=int, default=30)
    parser.add_argument('--poll_interval', type=int, default=5)
    parser.add_argument('--cloud_function_url', default=os.environ.get('CLOUD_FUNCTION_URL', ''))
    parser.add_argument('--log_level', default=os.environ.get('LOG_LEVEL', 'info'))

    args = parser.parse_args()

    if not args.engine:
        logging.error("ENGINE_COMMAND environment variable is required")
        exit(1)

    if not args.token:
        logging.error("LICHESS_API_TOKEN environment variable is required")
        exit(1)

    return args


def register_engine(args, http):
    res = ok(http.get(f"{args.lichess}/api/external-engine"))

    secret = secrets.token_urlsafe(32)

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
    supported_variants = ["chess"]

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


def poll_for_work(args, http, secret):
    logging.info("Starting the work polling loop")
    while True:
        try:
            res = http.post(
                f"{args.broker}/api/external-engine/work",
                json={"providerSecret": secret},
                timeout=args.poll_timeout  # Set a longer timeout for long polling
            )
            if res.status_code == 200:
                job = res.json()
                logging.info("Work received: %s", job["id"])
                # Invoke the cloud function to process the job
                invoke_cloud_function(args.cloud_function_url, job)
            else:
                logging.info("No work available, retrying immediately")
        except requests.exceptions.Timeout:
            logging.info("Long polling timeout, retrying immediately")
        except Exception as e:
            logging.error("Error while polling for work: %s", e)
            time.sleep(args.poll_interval)  # Wait before retrying in case of an error

            
def invoke_cloud_function(cloud_function_url, job):
    try:
        res = requests.post(cloud_function_url, json=job)
        res.raise_for_status()
        logging.info("Cloud function invoked successfully")
    except requests.exceptions.RequestException as err:
        logging.error("Error invoking cloud function: %s", err)

def main():
    args = get_args()
    http = setup_http_session(args.token)
    secret = register_engine(args, http)
    threading.Thread(target=poll_for_work, args=(args, http, secret), daemon=True).start()

    # Keep the main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("Shutting down gracefully.")

if __name__ == "__main__":
    main()
