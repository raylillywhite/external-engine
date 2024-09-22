import logging
import requests
import time
import threading

from engine_utils import (
    get_args,
    setup_http_session,
    register_engine,
    invoke_cloud_function,
)

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
    # Start the polling thread
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
