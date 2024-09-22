FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY main.py .
COPY engine_utils.py .

ENTRYPOINT ["python", "main.py"]