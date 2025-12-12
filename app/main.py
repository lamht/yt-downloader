import os
import uuid
import logging
import traceback
import subprocess
from threading import Thread, Lock
from urllib.parse import quote, unquote

from flask import (
    Flask, render_template, request, send_from_directory,
    redirect, flash, get_flashed_messages, jsonify, Response
)
from flask_socketio import SocketIO

from downloader import download_video, get_video_info

# ---------- Setup ----------
logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-me")
socketio = SocketIO(app, cors_allowed_origins="*")
app.logger.setLevel(logging.INFO)
logger = logging.getLogger("main")
logger.setLevel(logging.INFO)

# ---------- Download tracking ----------
_downloads = {}
_downloads_lock = Lock()

def _new_download_key():
    return uuid.uuid4().hex

def _set_download(key: str, data: dict):
    with _downloads_lock:
        _downloads[key] = {**_downloads.get(key, {}), **data}

def _get_download(key: str):
    with _downloads_lock:
        return _downloads.get(key)

# ---------- File processor ----------
def process_file(src_path: str, dst_dir: str) -> str:
    DST_DIR = "/app/download"
    full_dir = os.path.join(DST_DIR, dst_dir)
    os.makedirs(full_dir, exist_ok=True)
    filename = os.path.basename(src_path)
    name, ext = os.path.splitext(filename)
    name = name[:100]
    name = quote(name)
    filename = name + ext
    ext = ext.lower()

    # choose output
    if ext == ".mp4":
        dst = os.path.join(DST_DIR, dst_dir, f"{name}.aac")
        cmd = ["ffmpeg", "-i", src_path, "-map", "a", "-c:a", "copy", "-y", dst]

    elif ext == ".m4a":
        dst = os.path.join(DST_DIR, dst_dir, f"{name}.aac")
        cmd = ["ffmpeg", "-i", src_path, "-c", "copy", "-y", dst]

    elif ext in (".opus", ".webm"):
        dst = os.path.join(DST_DIR, dst_dir, f"{name}.mp3")
        cmd = ["ffmpeg", "-i", src_path, "-map", "a", "-q:a", "0", "-y", dst]

    else:
        dst = os.path.join(DST_DIR, dst_dir, filename)
        cmd = ["ffmpeg", "-i", src_path, "-c", "copy", "-y", dst]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        app.logger.error("ffmpeg failed: %s", proc.stderr)
        raise RuntimeError(proc.stderr)

    return dst

# ---------- Main page ----------
@app.route("/", methods=["GET", "POST"])
def index():
    filepath = None
    title = None
    formats = None
    error = None

    if request.method == "POST":
        action = request.form.get("action")
        url = request.form.get("url")

        if not url:
            flash("URL is required", "error")
            return redirect(request.url)

        try:
            # Inspect mode
            if action == "inspect" or not action:
                info = get_video_info(url)
                formats = info.get("formats")
                title = info.get("title")

            # Download mode
            elif action == "download":
                format_id = request.form.get("format_id") or None
                audio_only = request.form.get("audio_only") == "1"

                info = get_video_info(url)
                title = info.get("title")

                key = _new_download_key()
                _set_download(key, {"status": "queued", "title": title})

                socketio.emit("download_started", {
                    "key": key,
                    "title": title,
                    "message": "Queued"
                })

                def bg_download(k, u, fmt, audio):
                    try:
                        _set_download(k, {"status": "downloading"})
                        socketio.emit("download_status", {
                            "key": k,
                            "status": "downloading",
                            "message": "Starting download..."
                        })

                        # run yt-dlp
                        result = download_video(u, format_id=fmt, audio_only=audio)
                        tmp = result["filepath"]

                        socketio.emit("download_status", {
                            "key": k,
                            "status": "downloaded",
                            "message": "Download complete. Processing..."
                        })

                        # process with ffmpeg
                        aac_path = process_file(tmp, "aac")
                        logger.info("Processed file saved to: %s", aac_path)
                        _set_download(k, {"status": "done", "filepath": aac_path})

                        file_name = quote(os.path.basename(aac_path))
                        download_url = f"/download/aac/{file_name}"

                        socketio.emit("download_complete", {
                            "key": k,
                            "status": "success",
                            "download_url": download_url,
                            "title": result.get("title"),
                            "message": "Ready"
                        })

                    except Exception as e:
                        tb = traceback.format_exc()
                        app.logger.error("Background error: %s\n%s", e, tb)
                        _set_download(k, {"status": "error", "error": str(e)})
                        socketio.emit("download_complete", {
                            "key": k,
                            "status": "error",
                            "message": str(e)
                        })

                Thread(target=bg_download, daemon=True,
                       args=(key, url, format_id, audio_only)).start()

                return jsonify({"status": "queued", "key": key})

        except Exception as e:
            error = str(e)
            flash(error, "error")
            return redirect(request.url)

    flashed = get_flashed_messages(with_categories=True)
    return render_template("index.html",
                           filepath=filepath,
                           title=title,
                           formats=formats,
                           error=error,
                           flashed=flashed)

# ---------- File download ----------
@app.route("/download/aac/<path:filename>")
def download_aac(filename):
    DST_DIR = "/app/download/aac"
    
    path = os.path.join(DST_DIR, filename)
    logger.info("Serving file: %s", path)
    if not os.path.exists(path):
        return "File not found", 404
    
    file_size = os.path.getsize(path)

    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{filename}",
        "Content-Length": str(file_size),
        "Content-Type": "application/octet-stream"
    }

    def generate():
        with open(path, "rb") as f:
            chunk_size = 8192
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    return Response(generate(), headers=headers)

# ---------- Run ----------
if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
