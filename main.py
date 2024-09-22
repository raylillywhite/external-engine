import logging
import requests
import time
import os

from engine_utils import (
    get_args,
    setup_http_session,
    register_engine,
    invoke_cloud_function,
)

def main():
    args = get_args()
    http = setup_http_session(args.token)
    secret = register_engine(args, http)

    logging.info("Starting the work polling loop")
    while True:
        try:
            res = http.post(
                f"{args.broker}/api/external-engine/work",
                json={"providerSecret": secret},
                timeout=12
            )
            if res.status_code == 200:
                job = res.json()
                logging.info("Work received: %s", job["id"])
                # Invoke the cloud function to process the job
                invoke_cloud_function(args.cloud_function_url, job)
            else:
                logging.info("No work available, retrying in %s seconds", args.poll_interval)
                time.sleep(args.poll_interval)
        except Exception as e:
            logging.error("Error while polling for work: %s", e)
            time.sleep(args.poll_interval)

if __name__ == "__main__":
    main()
