from flask import Flask, render_template, request, send_file, redirect, url_for, flash, get_flashed_messages
from flask_socketio import SocketIO, emit
from downloader import download_video, get_video_info
import os
import logging
import traceback
import subprocess
import uuid
from threading import Thread, Lock

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
    Process file based on format:
    - MP4: extract audio (copy codec, no encode) -> .m4a
    - M4A: copy audio (no encode)
    - OPUS/WEBM: encode to mp3
    - Other: copy as-is
    """
    os.makedirs(dst_dir, exist_ok=True)
    
    filename = os.path.basename(src_path)
    name_without_ext = os.path.splitext(filename)[0]
    ext = os.path.splitext(filename)[1].lower()
    
    app.logger.info("Processing %s (ext: %s)", filename, ext)
    
    try:
        if ext == ".mp4":
            dst_filename = f"{name_without_ext}.m4a"
            dst_path = os.path.join(dst_dir, dst_filename)
            cmd = ["ffmpeg", "-i", src_path, "-map", "a", "-c:a", "copy", "-y", dst_path]
        elif ext == ".m4a":
            dst_path = os.path.join(dst_dir, filename)
            cmd = ["ffmpeg", "-i", src_path, "-c", "copy", "-y", dst_path]
        elif ext in (".opus", ".webm"):
            dst_filename = f"{name_without_ext}.mp3"
            dst_path = os.path.join(dst_dir, dst_filename)
            cmd = ["ffmpeg", "-i", src_path, "-map", "a", "-q:a", "0", "-y", dst_path]
        else:
            dst_path = os.path.join(dst_dir, filename)
            cmd = ["ffmpeg", "-i", src_path, "-c", "copy", "-y", dst_path]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            app.logger.error("ffmpeg failed: %s", result.stderr)
            raise RuntimeError(f"ffmpeg failed: {result.stderr}")
        app.logger.info("Processed file -> %s", dst_path)
        return dst_path
    except Exception:
        tb = traceback.format_exc()
        app.logger.error("process_file failed: %s", tb)
        raise

@app.route("/", methods=["GET", "POST"])
def index():
    filepath = None
    title = None
    formats = None
    error = None

    app.logger.info("Request method: %s", request.method)
    if request.method == "POST":
        action = request.form.get("action")
        url = request.form.get("url")
        app.logger.info("Form action=%s url=%s", action, url)

        if not url:
            msg = "URL is required"
            app.logger.warning(msg)
            flash(msg, "error")
            return redirect(url_for("index"))

        try:
            if action == "inspect" or not action:
                app.logger.info("Inspecting URL")
                info = get_video_info(url)
                formats = info.get("formats")
                title = info.get("title")
                app.logger.info("Found %d formats for %s", len(formats or []), title)
            elif action == "download":
                format_id = request.form.get("format_id") or None
                audio_only = request.form.get("audio_only") == "1"
                app.logger.info("Downloading url=%s format_id=%s audio_only=%s", url, format_id, audio_only)
                
                # create unique key and register
                key = _new_download_key()
                _set_download(key, {"status": "queued", "title": title or url, "filepath": None})
                socketio.emit("download_started", {"key": key, "message": "Queued", "title": title or url})
                
                def download_bg(k=key, u=url, fmt=format_id, audio=audio_only):
                    try:
                        _set_download(k, {"status": "downloading"})
                        socketio.emit("download_status", {"key": k, "status": "downloading", "message": "Starting download..."})
                        
                        result = download_video(u, format_id=fmt, audio_only=audio)
                        _set_download(k, {"status": "downloaded", "tmp_filepath": result.get("filepath")})
                        socketio.emit("download_status", {"key": k, "status": "downloaded", "message": "Download finished, processing..."})
                        
                        # process and move to acc
                        acc_path = process_file(result.get("filepath"), "acc")
                        _set_download(k, {"status": "done", "filepath": acc_path})
                        
                        with app.app_context():
                            download_url = url_for('download', folder='acc', filename=os.path.basename(acc_path))
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
                
                thread = Thread(target=download_bg, daemon=True)
                thread.start()
                
                flash("Download queued", "info")
                return redirect(url_for("index"))
        except Exception as e:
            tb = traceback.format_exc()
            app.logger.error("Exception handling request: %s\n%s", str(e), tb)
            error = str(e) + "\n\n" + tb
            flash(str(e), "error")

    flashed = get_flashed_messages(with_categories=True)
    return render_template("index.html", filepath=filepath, title=title, formats=formats, error=error, flashed=flashed)

@app.route("/download/<folder>/<path:filename>")
def download(folder, filename):
    # only allow serving from these folders
    if folder not in ("acc", "downloads"):
        return "Invalid folder", 400
    base = os.path.abspath(folder)
    abspath = os.path.abspath(os.path.join(folder, filename))
    if not abspath.startswith(base + os.sep) and abspath != base:
        return "Forbidden", 403
    if os.path.exists(abspath):
        return send_file(abspath, as_attachment=True)
    else:
        return "File not found", 404

@socketio.on("connect")
def handle_connect():
    app.logger.info("Client connected")
    emit("response", {"data": "Connected"})

@socketio.on("disconnect")
def handle_disconnect():
    app.logger.info("Client disconnected")

if __name__ == "__main__":
    os.makedirs("downloads", exist_ok=True)
    os.makedirs("acc", exist_ok=True)
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, allow_unsafe_werkzeug=True)