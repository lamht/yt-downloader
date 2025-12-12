# Base image nhẹ, Python 3.14
FROM python:3.14-slim

# Set working directory
WORKDIR /app

# Cài build tools, dev libs & ffmpeg trước pip
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    gcc \
    git \
    libffi-dev \
    libssl-dev \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements
COPY requirements.txt .

# Upgrade pip & cài dependencies
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ source code
COPY . .

# Expose cổng Flask
EXPOSE 5000

# Chạy Flask app
CMD ["python", "app/main.py"]
