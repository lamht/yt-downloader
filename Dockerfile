# ---------- Deno Engine Binary Loader ----------
FROM denoland/deno:bin-2.1.9 AS deno-bin

# ---------- Main App Stage ----------
FROM python:3.11-slim

# Copy the Deno binary from its official root path to your runtime's system PATH
COPY --from=deno-bin /deno /usr/local/bin/deno

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Environment variables
ENV ENABLE_DENO=true
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

CMD ["python", "main.py"]
