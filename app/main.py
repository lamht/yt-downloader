from flask import Flask, render_template, request, send_file, redirect, url_for, flash, get_flashed_messages
from downloader import download_video, get_video_info
import os
import logging
import traceback

logging.basicConfig(level=logging.INFO)
app = Flask(__name__)
app.logger.setLevel(logging.INFO)
app.secret_key = os.environ.get("FLASK_SECRET", "change-me")

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
                result = download_video(url, format_id=format_id, audio_only=audio_only)
                filepath = result.get("filepath")
                title = result.get("title")
                app.logger.info("Download complete: filepath=%s, title=%s", filepath, title)
                flash(f"Downloaded: {title}", "success")
        except Exception as e:
            tb = traceback.format_exc()
            app.logger.error("Exception handling request: %s\n%s", str(e), tb)
            error = str(e) + "\n\n" + tb
            flash(str(e), "error")

    # surface flashed messages and error details to template
    flashed = get_flashed_messages(with_categories=True)
    return render_template("index.html", filepath=filepath, title=title, formats=formats, error=error, flashed=flashed)

@app.route("/download/<path:filename>")
def download(filename):
    # send absolute path to avoid cwd issues in container
    abspath = os.path.abspath(filename)
    if os.path.exists(abspath):
        return send_file(abspath, as_attachment=True)
    else:
        return "File not found", 404

if __name__ == "__main__":
    os.makedirs("downloads", exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=False)