import logging
import requests
import time
import threading
import os
import argparse

from engine_utils import (
    setup_http_session,
    register_engine,
    invoke_cloud_function,
)

def get_args():
    parser = argparse.ArgumentParser(description='Engine Arguments')
    parser.add_argument('--name', default=os.environ.get('ENGINE_NAME', 'Alpha 2'))
    parser.add_argument('--engine', default=os.environ.get('ENGINE_COMMAND'))
    parser.add_argument('--setoption', nargs='*', default=[])
    parser.add_argument('--lichess', default=os.environ.get('LICHESS_URL', 'https://lichess.org'))
    parser.add_argument('--broker', default=os.environ.get('BROKER_URL', 'https://engine.lichess.ovh'))
    parser.add_argument('--token', default=os.environ.get('LICHESS_API_TOKEN'))
    parser.add_argument('--provider_secret', default=os.environ.get('PROVIDER_SECRET'))
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
