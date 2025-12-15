import eventlet
eventlet.monkey_patch()

import os
import time
import uuid
import logging
import traceback
import subprocess
from threading import Lock
from urllib.parse import quote

from flask import (
    Flask, request, jsonify,
    send_from_directory, Response, make_response
)
from flask_socketio import SocketIO
from log_config import setup_logger

from downloader import download_video, get_video_info


# ---------- Setup ----------
app = Flask(__name__, static_folder="static", static_url_path="")
app.secret_key = os.environ.get("FLASK_SECRET", "change-me")

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="eventlet"
)

logger = setup_logger("main")
logger.info("Logger for main initialized")

# ---------- Download tracking ----------
_downloads = {}
_lock = Lock()

def _new_key():
    return uuid.uuid4().hex

def _set(k, data):
    with _lock:
        _downloads[k] = {**_downloads.get(k, {}), **data}

# ---------- File processor ----------
def process_file(src_path: str, dst_dir: str) -> str:
    DST_DIR = "/app/download"
    full_dir = os.path.join(DST_DIR, dst_dir)
    os.makedirs(full_dir, exist_ok=True)

    filename = os.path.basename(src_path)
    name, ext = os.path.splitext(filename)

    name = name[:70]
    ext = ext.lower()

    if ext == ".mp4":
        dst = os.path.join(full_dir, f"{name}.aac")
        cmd = ["ffmpeg", "-i", src_path, "-map", "a", "-c:a", "copy", "-y", dst]

    elif ext == ".m4a":
        dst = os.path.join(full_dir, f"{name}.aac")
        cmd = ["ffmpeg", "-i", src_path, "-c", "copy", "-y", dst]

    elif ext in (".opus", ".webm"):
        dst = os.path.join(full_dir, f"{name}.mp3")
        cmd = ["ffmpeg", "-i", src_path, "-map", "a", "-q:a", "0", "-y", dst]

    else:
        dst = os.path.join(full_dir, f"{name}{ext}")
        cmd = ["ffmpeg", "-i", src_path, "-c", "copy", "-y", dst]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr)

    return dst

# ---------- Routes ----------

@app.route("/")
def index():
    response = make_response(send_from_directory("templates", "index.html"))
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route("/inspect", methods=["POST"])
def inspect():
    data = request.json or request.form
    url = data.get("url")

    if not url:
        return jsonify({"error": "URL is required"}), 400

    info = get_video_info(url)

    return jsonify({
        "title": info.get("title"),
        "formats": info.get("formats", [])
    })

@app.route("/download", methods=["POST"])
def download():
    data = request.json or request.form

    url = data.get("url")
    format_id = data.get("format_id") or None
    audio_only = str(data.get("audio_only", "0")) == "1"

    if not url:
        return jsonify({"error": "URL is required"}), 400

    key = _new_key()
    _set(key, {"status": "queued"})

    socketio.emit("download_started", {
        "key": key,
        "status": "queued"
    })

    def bg_download():
        time.sleep(2)  # <-- sửa từ asyncio.sleep(2) thành time.sleep(2)
        try:
            _set(key, {"status": "downloading"})
            socketio.emit("download_status", {
                "key": key,
                "status": "downloading",
                "message": "Downloading..."
            })

            result = download_video(
                url,
                format_id=format_id,
                audio_only=audio_only
            )

            socketio.emit("download_status", {
                "key": key,
                "status": "processing",
                "message": "Processing..."
            })

            final_path = process_file(result["filepath"], "aac")
            file_name = quote(os.path.basename(final_path))

            _set(key, {
                "status": "done",
                "filepath": final_path
            })

            socketio.emit("download_complete", {
                "key": key,
                "status": "done",
                "download_url": f"/download/aac/{file_name}"
            })

        except Exception as e:
            logger.error(traceback.format_exc())
            _set(key, {"status": "error", "error": str(e)})

            socketio.emit("download_complete", {
                "key": key,
                "status": "error",
                "message": str(e)
            })

    socketio.start_background_task(bg_download)

    return jsonify({
        "key": key,
        "status": "queued"
    })

@app.route("/download/aac/<path:filename>")
def download_aac(filename):
    DST_DIR = "/app/download/aac"
    path = os.path.join(DST_DIR, filename)

    if not os.path.exists(path):
        return "File not found", 404

    ascii_filename = ''.join(
        c if ord(c) < 128 else '_'
        for c in filename
    )
    safe_filename = quote(filename)

    file_size = os.path.getsize(path)

    headers = {
        "Content-Disposition":
            f"attachment; filename='{ascii_filename}'; "
            f"filename*=UTF-8''{safe_filename}",
        "Content-Length": str(file_size),
        "Content-Type": "application/octet-stream"
    }

    def generate():
        with open(path, "rb") as f:
            while True:
                chunk = f.read(8192)
                if not chunk:
                    break
                yield chunk

    return Response(generate(), headers=headers)

# ---------- Run ----------
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000)