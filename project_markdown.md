# YouTube Downloader Project (yt-dlp + Python + Web UI + Docker)

This project provides a clean and deployable YouTube downloader with:
- Python backend (Flask)
- yt-dlp integration
- Simple HTML Web UI
- Full Docker support

---

## 📁 Project Structure
```
yt-downloader/
│── app/
│   ├── main.py
│   ├── downloader.py
│   ├── templates/
│   │     └── index.html
│   └── static/
│         └── style.css
│
│── requirements.txt
│── Dockerfile
│── docker-compose.yml
```

---

## 🧩 downloader.py
```python
import yt_dlp

def download_video(url: str, out_dir="downloads"):
    ydl_opts = {
        "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
        "format": "mp4",
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return {
            "title": info.get("title"),
            "filepath": ydl.prepare_filename(info)
        }
```

---

## 🖥 main.py
```python
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
```

---

## 🌐 index.html
```html
<!DOCTYPE html>
<html>
<head>
    <title>YouTube Downloader</title>
</head>
<body>
    <h2>YouTube Downloader</h2>
    <form method="POST">
        <input type="text" name="url" placeholder="Paste YouTube URL" style="width:300px">
        <button type="submit">Download</button>
    </form>

    {% if filepath %}
        <p>Downloaded: {{ title }}</p>
        <a href="/download/{{ filepath }}">Click to Download File</a>
    {% endif %}
</body>
</html>
```

---

## 📦 requirements.txt
```
flask
yt-dlp
```

---

## 🐳 Dockerfile
```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt update && apt install -y ffmpeg

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY ./app ./app

WORKDIR /app
CMD ["python", "main.py"]
```

---

## 🐳 docker-compose.yml
```yaml
version: "3.8"

services:
  ytdownloader:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./downloads:/app/downloads
```

---

## 🚀 Run with Docker
### Build
```
docker build -t yt-ui .
```

### Run
```
docker run -it -p 5000:5000 -v $PWD/downloads:/app/downloads yt-ui
```

Then open:
```
http://localhost:5000
```

---

If you want, I can also:
- Generate a GitHub README.md
- Add MP3 download / choose format
- Add API version
- Create a better UI with Tailwind/Bootstrap