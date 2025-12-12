# Base image nhẹ, Python 3.14
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Cài build tools & ffmpeg để yt-dlp và các package cần C extension compile được
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    git \
    ffmpeg \
    libffi-dev \
    libssl-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements
COPY requirements.txt .

# Upgrade pip & cài dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ source code
COPY . .

# Expose cổng Flask
EXPOSE 5000

# Command chạy Flask app
CMD ["python", "app/main.py"]
