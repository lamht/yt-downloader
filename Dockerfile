# ---------- Stage 1: Grab Deno Binary ----------
FROM denoland/deno:bin-2.1.9 AS deno-bin

# ---------- Stage 2: Final Production Image ----------
FROM python:3.11-slim

WORKDIR /app

# ---------- Metadata ----------
LABEL maintainer="yt-downloader" \
      description="YouTube video downloader with FastAPI and JavaScript runtime support" \
      version="1.0.0"

# ---------- Python & App environment optimizations ----------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=2 \
    ENV=production \
    PORT=5000

# ---------- Copy Deno from Stage 1 ----------
# This satisfies the requirement for a JS engine (like Deno) without bloated manual installs
COPY --from=deno-bin /usr/local/bin/deno /usr/local/bin/deno

# ---------- System dependencies ----------
# Installs the actual FFmpeg binary (not the python package) and utilities
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
 && rm -rf /var/lib/apt/lists/* \
 && apt-get clean

# ---------- Python dependencies ----------
COPY requirements.txt .
RUN pip install --upgrade pip setuptools \
 && pip install --no-cache-dir -r requirements.txt

# ---------- Create non-root user for security ----------
RUN useradd -m -u 1000 downloader \
 && chown -R downloader:downloader /app
USER downloader

# ---------- App source ----------
COPY --chown=downloader:downloader . .

EXPOSE 5000

# ---------- Run app (Uvicorn + asyncio) ----------
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-5000} --log-level warning"]
