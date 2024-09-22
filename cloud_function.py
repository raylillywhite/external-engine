import logging
import functions_framework
import os
import argparse

from engine_utils import handle_job, Engine, ok

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
    parser.add_argument('--log_level', default=os.environ.get('LOG_LEVEL', 'info'))

    args = parser.parse_args()

    if not args.engine:
        logging.error("ENGINE_COMMAND environment variable is required")
        exit(1)

    if not args.token:
        logging.error("LICHESS_API_TOKEN environment variable is required")
        exit(1)

    return args

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