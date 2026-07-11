# ---------- Stage 1: Grab Deno Binary ----------
FROM denoland/deno:bin-2.1.9 AS deno-bin

# ---------- Stage 2: Final Production Image ----------
FROM python:3.11-slim

WORKDIR /app

# ---------- Metadata ----------
LABEL maintainer="yt-downloader" \
      description="YouTube video downloader with FastAPI and Deno JS engine support" \
      version="1.0.0"

# ---------- Runtime & Framework Optimizations ----------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=2 \
    ENV=production \
    PORT=5000 \
    ENABLE_DENO=true \
    DEBIAN_FRONTEND=noninteractive

# ---------- Extract JS Engine Dependency ----------
# Copy from the actual root path (/deno) used by official denoland binaries
COPY --from=deno-bin /deno /usr/local/bin/deno

# ---------- System & Build dependencies ----------
RUN apt-get update \
 && apt-get install -y -o Acquire::Retries=3 --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    gcc \
    python3-dev \
    build-essential \
 && rm -rf /var/lib/apt/lists/* \
 && apt-get clean

# ---------- Python dependencies ----------
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel \
 && pip install --no-cache-dir -r requirements.txt

# ---------- Create non-root user for security ----------
# Chowning the /app directory BEFORE copying the files prevents Docker 
# from creating a duplicate filesystem layer, saving build time and size.
RUN useradd -m -u 1000 downloader \
 && chown -R downloader:downloader /app

# ---------- App source ----------
COPY --chown=downloader:downloader . .

USER downloader

EXPOSE 5000

# ---------- Run app (Uvicorn + asyncio) ----------
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-5000} --log-level warning"]
