FROM --platform=linux/amd64 python:3.10-slim AS build

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py .

ENTRYPOINT ["python", "main.py"]