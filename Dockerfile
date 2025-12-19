FROM python:3.11-slim

WORKDIR /app

# ---------- Python runtime optimizations ----------
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENV=production \
    PORT=5000

# ---------- System dependencies ----------
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
 && rm -rf /var/lib/apt/lists/*

# ---------- Python dependencies ----------
COPY requirements.txt .
RUN pip install --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ---------- App source ----------
COPY . .

EXPOSE 5000

# ---------- Run app (Gunicorn + eventlet, dynamic PORT) ----------
CMD ["sh", "-c", "gunicorn app.main:app -k eventlet -w 1 --bind 0.0.0.0:${PORT:-5000} --log-level warning"]
