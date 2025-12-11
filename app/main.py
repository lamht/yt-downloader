from flask import Flask, render_template, request, send_file, redirect, url_for, flash, get_flashed_messages
from flask_socketio import SocketIO, emit
from downloader import download_video, get_video_info
import os
import logging
import traceback
import subprocess
from threading import Thread

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.logger.setLevel(logging.INFO)
app.secret_key = os.environ.get("FLASK_SECRET", "change-me")
socketio = SocketIO(app, cors_allowed_origins="*")

def process_file(src_path: str, dst_dir: str) -> str:
    """
    Process file based on format:
    - MP4: extract audio (copy codec, no encode)
    - M4A: copy audio (no encode)
    - OPUS: extract audio to MP3 (with encode)
    - Other: copy as-is
    """
    os.makedirs(dst_dir, exist_ok=True)
    
    filename = os.path.basename(src_path)
    name_without_ext = os.path.splitext(filename)[0]
    ext = os.path.splitext(filename)[1].lower()
    
    app.logger.info("Processing %s (ext: %s)", filename, ext)
    
    try:
        if ext == ".mp4":
            # MP4: extract audio, copy codec (no re-encode)
            dst_filename = f"{name_without_ext}.m4a"
            dst_path = os.path.join(dst_dir, dst_filename)
            app.logger.info("MP4 detected - extracting audio (copy codec) to %s", dst_path)
            
            cmd = [
                "ffmpeg",
                "-i", src_path,
                "-map", "a",  # extract audio only
                "-c:a", "copy",  # copy audio codec (no re-encode)
                "-y",  # overwrite
                dst_path
            ]
        
        elif ext == ".m4a":
            # M4A: copy as-is (no encode)
            dst_path = os.path.join(dst_dir, filename)
            app.logger.info("M4A detected - copying audio (no encode) to %s", dst_path)
            
            cmd = [
                "ffmpeg",
                "-i", src_path,
                "-c", "copy",  # copy all codecs
                "-y",
                dst_path
            ]
        
        elif ext == ".opus" or ext == ".webm":
            # OPUS/WEBM: encode to MP3
            dst_filename = f"{name_without_ext}.mp3"
            dst_path = os.path.join(dst_dir, dst_filename)
            app.logger.info("OPUS/WEBM detected - encoding audio to %s", dst_path)
            
            cmd = [
                "ffmpeg",
                "-i", src_path,
                "-q:a", "0",  # best quality
                "-map", "a",
                "-y",
                dst_path
            ]
        
        else:
            # Other formats: copy as-is
            dst_path = os.path.join(dst_dir, filename)
            app.logger.info("Other format - copying to %s", dst_path)
            
            cmd = [
                "ffmpeg",
                "-i", src_path,
                "-c", "copy",
                "-y",
                dst_path
            ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode == 0:
            app.logger.info("Successfully processed to %s", dst_path)
            return dst_path
        else:
            app.logger.error("ffmpeg error: %s", result.stderr)
            raise RuntimeError(f"ffmpeg failed: {result.stderr}")
    
    except subprocess.TimeoutExpired:
        raise RuntimeError("ffmpeg operation timeout")
    except Exception as e:
        app.logger.error("Processing failed: %s", e)
        raise RuntimeError(f"Failed to process file: {e}")

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
                
                # Start download in background thread and emit via WebSocket
                def download_bg():
                    try:
                        socketio.emit("download_status", {"status": "downloading", "message": "Starting download..."})
                        result = download_video(url, format_id=format_id, audio_only=audio_only)
                        
                        # Process file to acc folder
                        socketio.emit("download_status", {"status": "processing", "message": "Processing file..."})
                        acc_path = process_file(result.get("filepath"), "acc")
                        
                        socketio.emit("download_complete", {
                            "status": "success",
                            "filepath": acc_path,
                            "title": result.get("title"),
                            "message": f"Done: {result.get('title')}"
                        })
                    except Exception as e:
                        app.logger.error("Download error: %s", e)
                        socketio.emit("download_complete", {
                            "status": "error",
                            "message": str(e)
                        })
                
                thread = Thread(target=download_bg, daemon=True)
                thread.start()
                
                flash("Download started...", "info")
                return redirect(url_for("index"))
        except Exception as e:
            tb = traceback.format_exc()
            app.logger.error("Exception handling request: %s\n%s", str(e), tb)
            error = str(e) + "\n\n" + tb
            flash(str(e), "error")

    flashed = get_flashed_messages(with_categories=True)
    return render_template("index.html", filepath=filepath, title=title, formats=formats, error=error, flashed=flashed)

@app.route("/download/<path:filename>")
def download(filename):
    abspath = os.path.abspath(filename)
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
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)