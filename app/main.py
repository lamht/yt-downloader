from flask import Flask, render_template, request, send_file, redirect, flash, get_flashed_messages
from flask_socketio import SocketIO
from downloader import download_video, get_video_info
import os
import logging
import traceback
import subprocess
import uuid
from threading import Thread, Lock
from urllib.parse import quote
from flask import jsonify

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.logger.setLevel(logging.INFO)
app.secret_key = os.environ.get("FLASK_SECRET", "change-me")
socketio = SocketIO(app, cors_allowed_origins="*")

# in-memory map to track downloads by key
_downloads: dict = {}
_downloads_lock = Lock()

def _new_download_key() -> str:
    return uuid.uuid4().hex

def _set_download(key: str, data: dict):
    with _downloads_lock:
        _downloads[key] = {**_downloads.get(key, {}), **data}

def _get_download(key: str) -> dict | None:
    with _downloads_lock:
        return _downloads.get(key)

def process_file(src_path: str, dst_dir: str) -> str:
    """
    Process file based on extension:
    - .mp4 -> extract audio (copy codec) -> .m4a
    - .m4a -> copy as-is
    - .opus/.webm -> encode to .mp3
    - other -> copy as-is
    """
    os.makedirs(dst_dir, exist_ok=True)
    filename = os.path.basename(src_path)
    name, ext = os.path.splitext(filename)
    ext = ext.lower()

    if ext == ".mp4":
        dst = os.path.join(dst_dir, f"{name}.m4a")
        cmd = ["ffmpeg", "-i", src_path, "-map", "a", "-c:a", "copy", "-y", dst]
    elif ext == ".m4a":
        dst = os.path.join(dst_dir, filename)
        cmd = ["ffmpeg", "-i", src_path, "-c", "copy", "-y", dst]
    elif ext in (".opus", ".webm"):
        dst = os.path.join(dst_dir, f"{name}.mp3")
        cmd = ["ffmpeg", "-i", src_path, "-map", "a", "-q:a", "0", "-y", dst]
    else:
        dst = os.path.join(dst_dir, filename)
        cmd = ["ffmpeg", "-i", src_path, "-c", "copy", "-y", dst]

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        app.logger.error("ffmpeg failed: %s", proc.stderr)
        raise RuntimeError(proc.stderr)
    app.logger.info("Processed file -> %s", dst)
    return dst

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
            if action == "inspect" or not action:
                info = get_video_info(url)
                formats = info.get("formats")
                title = info.get("title")
            elif action == "download":
                format_id = request.form.get("format_id") or None
                audio_only = request.form.get("audio_only") == "1"

                key = _new_download_key()
                _set_download(key, {"status": "queued", "title": title or url})
                
                client_sid = request.sid
                socketio.emit("download_started", {"key": key, "title": title or url, "message": "Queued"}, to=client_sid)

                def download_bg(k=key, u=url, fmt=format_id, audio=audio_only):
                    try:
                        _set_download(k, {"status": "downloading"})
                        socketio.emit("download_status", {"key": k, "status": "downloading", "message": "Starting download..."})

                        result = download_video(u, format_id=fmt, audio_only=audio)
                        _set_download(k, {"status": "downloaded", "tmp_filepath": result.get("filepath")})
                        socketio.emit("download_status", {"key": k, "status": "downloaded", "message": "Download finished, processing..."})

                        acc_path = process_file(result.get("filepath"), "acc")
                        _set_download(k, {"status": "done", "filepath": acc_path})

                        # build safe relative URL (no url_for required)
                        safe_name = quote(os.path.basename(acc_path), safe='')
                        download_url = f"/download/acc/{safe_name}"

                        socketio.emit("download_complete", {
                            "key": k,
                            "status": "success",
                            "download_url": download_url,
                            "filepath": acc_path,
                            "title": result.get("title"),
                            "message": "Ready"
                        })
                    except Exception as e:
                        tb = traceback.format_exc()
                        app.logger.error("Background download failed: %s\n%s", e, tb)
                        _set_download(k, {"status": "error", "error": str(e)})
                        socketio.emit("download_complete", {"key": k, "status": "error", "message": str(e)})
                # start download in background thread
                Thread(target=download_bg, daemon=True).start()

                # Return JSON response with the key so client knows which key to track
                return jsonify({"status": "queued", "key": key})
        except Exception as e:
            app.logger.error("Error processing request: %s", e)
            error = str(e)
            flash(error, "error")
            return redirect(request.url)

    flashed = get_flashed_messages(with_categories=True)
    return render_template("index.html", filepath=filepath, title=title, formats=formats, error=error, flashed=flashed)