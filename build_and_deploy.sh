#!/bin/bash
docker build -t look-for-work look-for-work && docker tag look-for-work gcr.io/cloud-stockfish-436405/look-for-work && docker push gcr.io/cloud-stockfish-436405/look-for-work

gcloud functions deploy do-work \
  --runtime python310 \
  --entry-point handle_job_request \
  --trigger-http \
  --allow-unauthenticated \
  --memory 4GB \
  --cpu 8 \
  --timeout 540s \
  --source do-work \
  --set-env-vars ENGINE_COMMAND=./stockfish-ubuntu-x86-64-avx2,LICHESS_API_TOKEN=$LICHESS_API_TOKEN \
  --project cloud-stockfish-436405