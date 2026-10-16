FROM python:3.15-slim

COPY . app/.

WORKDIR /app

RUN ["pip", "install", "--no-cache-dir", "-r", "requirements.txt"]

ENTRYPOINT ["python", "main.py"]