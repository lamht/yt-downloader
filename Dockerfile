FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# App source
COPY . .

# Env for unbuffered stdout
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# Run Python unbuffered
CMD ["python", "-u", "app/main.py"]