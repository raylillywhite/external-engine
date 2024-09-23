#!/bin/bash
docker build -t look-for-work look-for-work && docker tag look-for-work gcr.io/cloud-stockfish-436405/look-for-work && docker push gcr.io/cloud-stockfish-436405/look-for-work

gcloud compute instances reset look-for-work --zone asia-east1-a --project cloud-stockfish-436405

gcloud functions deploy do-work \
  --runtime python310 \
  --entry-point handle_job_request \
  --trigger-http \
  --allow-unauthenticated \
  --memory 16Gi \
  --cpu 8 \
  --timeout 540s \
  --region asia-east1 \
  --source do-work \
  --set-env-vars ENGINE_COMMAND=./stockfish-ubuntu-x86-64-avx2,LICHESS_API_TOKEN=$LICHESS_API_TOKEN \
  --project cloud-stockfish-436405
