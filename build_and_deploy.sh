#!/bin/bash
docker build -t look-for-work . && docker tag look-for-work gcr.io/cloud-stockfish-436405/look-for-work && docker push gcr.io/cloud-stockfish-436405/look-for-work