FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get update && apt-get install -y ffmpeg && \
    apt-get clean

COPY . .

EXPOSE 5000

CMD ["python", "app/main.py"]