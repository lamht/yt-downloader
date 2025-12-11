FROM python:3.11-slim

WORKDIR /app

RUN apt update && apt install -y ffmpeg

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

WORKDIR /app
CMD ["python", "main.py"]