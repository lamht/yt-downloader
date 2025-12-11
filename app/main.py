from flask import Flask, render_template, request, send_file, redirect, url_for, flash
from downloader import download_video, get_video_info
import os

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "change-me")

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
            return redirect(url_for("index"))

        if action == "inspect":
            try:
                info = get_video_info(url)
                formats = info["formats"]
                title = info["title"]
            except Exception as e:
                error = str(e)
        elif action == "download":
            format_id = request.form.get("format_id") or None
            audio_only = request.form.get("audio_only") == "1"
            try:
                result = download_video(url, format_id=format_id, audio_only=audio_only)
                filepath = result["filepath"]
                title = result["title"]
            except Exception as e:
                error = str(e)

    return render_template("index.html", filepath=filepath, title=title, formats=formats, error=error)

@app.route("/download/<path:filename>")
def download(filename):
    # send absolute path to avoid cwd issues in container
    abspath = os.path.abspath(filename)
    return send_file(abspath, as_attachment=True)

if __name__ == "__main__":
    os.makedirs("downloads", exist_ok=True)
    app.run(host="0.0.0.0", port=5000)