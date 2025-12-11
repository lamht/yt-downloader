from flask import Flask, render_template, request, send_file
from downloader import download_video
import os

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    filepath = None
    title = None

    if request.method == "POST":
        url = request.form.get("url")
        result = download_video(url)
        filepath = result["filepath"]
        title = result["title"]

    return render_template("index.html", filepath=filepath, title=title)

@app.route("/download/<path:filename>")
def download(filename):
    return send_file(filename, as_attachment=True)

if __name__ == "__main__":
    os.makedirs("downloads", exist_ok=True)
    app.run(host="0.0.0.0", port=5000)