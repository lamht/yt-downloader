FROM python:3.11-slim

WORKDIR /app

# ---------- System dependencies ----------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    ca-certificates \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# ---------- Install Deno (JS runtime for yt-dlp) ----------
# RUN curl -fsSL https://deno.land/install.sh | sh
# ENV PATH="/root/.deno/bin:$PATH"
# ENV ENABLE_DENO=1
# ---------- Python dependencies ----------
COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---------- App source ----------
COPY . .

# ---------- Environment ----------
ENV PYTHONUNBUFFERED=1

EXPOSE 5000

# ---------- Run app ----------
CMD ["python", "-u", "app/main.py"]
