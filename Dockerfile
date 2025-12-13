FROM python:3.11-slim

WORKDIR /app

# System deps (chỉ giữ cái cần)
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

EXPOSE 5000

CMD ["python", "app/main.py"]