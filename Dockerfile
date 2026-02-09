FROM python:3.11-slim

WORKDIR /app

# ---------- Metadata ----------
LABEL maintainer="yt-downloader" \
      description="YouTube video downloader with FastAPI" \
      version="1.0.0"

# ---------- Python runtime optimizations ----------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONOPTIMIZE=2 \
    ENV=production \
    PORT=5000

# ---------- System dependencies ----------
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

# ---------- Health check ----------
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

# ---------- Run app (Uvicorn + asyncio) ----------
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-5000} --log-level warning"]

