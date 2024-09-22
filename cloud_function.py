import logging
import functions_framework
import os

from engine_utils import get_args, handle_job, Engine, ok

@functions_framework.http
def handle_job_request(request):
    job = request.get_json()
    if not job:
        logging.error("Invalid job data received")
        return "Invalid job data", 400

    try:
        args = get_args()
        engine = Engine(args)  # Initialize the engine
        handle_job(args, engine, job)  # Process the job
        return "Job processed successfully", 200
    except Exception as e:
        logging.error("Failed to process job: %s", e)
        return "Failed to process job", 500