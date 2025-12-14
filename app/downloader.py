import os
import glob
import logging
import subprocess
from urllib.parse import quote
import tempfile
import sys

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

# ---------- Logger riêng cho file này ----------
class FlushStreamHandler(logging.StreamHandler):
    def emit(self, record):
        super().emit(record)
        self.flush()  # đảm bảo mỗi log được flush ngay

logger = logging.getLogger("downloader")
logger.setLevel(logging.INFO)
if not logger.hasHandlers():
    ch = FlushStreamHandler(sys.stdout)
    formatter = logging.Formatter('[%(name)s] %(levelname)s: %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

# ---------- Cookie file from environment ----------
_cookie_file_path = None
def _get_cookie_file():
    global _cookie_file_path
    if _cookie_file_path is None:
        cookie_str = os.environ.get("COOKIE")
        if cookie_str:
            f = tempfile.NamedTemporaryFile(delete=False, mode="w", encoding="utf-8", suffix=".txt")
            f.write(cookie_str)
            f.flush()
            f.close()
            _cookie_file_path = f.name
            logger.info("Cookie file created: %s", _cookie_file_path)
    return _cookie_file_path

# ---------- yt-dlp utils ----------
WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

def _base_ydl_opts(extra: dict | None = None):
    opts = {
        "quiet": False,
        "no_warnings": False,
        #"user_agent": WINDOWS_UA,
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 3,
        "retry_sleep_functions": {
            "http": lambda n: 2 * n,
            "fragment": lambda n: 2 * n,
            "extractor": lambda n: 2 * n,
        },
        "socket_timeout": 30,
        "nocheckcertificate": True,
        "geo_bypass": True,
    }
    if extra:
        opts.update(extra)
    return opts

def get_video_info(url: str):
    """Inspect video formats"""
    logger.info("Inspecting URL: %s", url)  # <-- log URL

    ydl_opts = _base_ydl_opts({"noplaylist": True})
    cookie_file = _get_cookie_file()
    if cookie_file:
        ydl_opts["cookiefile"] = cookie_file
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title") or "download"
            formats = []
            for f in info.get("formats", []):
                formats.append({
                    "format_id": f.get("format_id"),
                    "ext": f.get("ext"),
                    "format": f.get("format"),
                    "format_note": f.get("format_note"),
                    "acodec": f.get("acodec"),
                    "vcodec": f.get("vcodec"),
                    "height": f.get("height"),
                    "width": f.get("width"),
                    "filesize": f.get("filesize") or f.get("filesize_approx"),
                    "tbr": f.get("tbr"),
                })
            logger.info("Found %d formats for %s", len(formats), title)
            return {"title": title, "formats": formats, "info": info}
    except Exception as e:
        logger.exception("get_video_info failed for URL: %s", url)
        raise RuntimeError(f"Failed to get video info: {e}")

def download_video(url: str, out_dir: str = "downloads", format_id: str | None = None, audio_only: bool = False):
    os.makedirs(out_dir, exist_ok=True)
    logger.info("Download called for URL: %s | format_id=%s | audio_only=%s", url, format_id, audio_only)
    cookie_file = _get_cookie_file()

    try_opts_list = []

    if format_id:
        opts = _base_ydl_opts({"outtmpl": f"{out_dir}/%(title)s.%(ext)s", "format": format_id, "noplaylist": True})
        if cookie_file:
            opts["cookiefile"] = cookie_file
        try_opts_list = [opts]
    elif audio_only:
        opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "bestaudio/best",
            "noplaylist": True,
            "postprocessors": [{"key": "FFmpegExtractAudio","preferredcodec": "aac","preferredquality": "192"}],
        })
        if cookie_file:
            opts["cookiefile"] = cookie_file
        try_opts_list = [opts]
    else:
        video_opts = _base_ydl_opts({"outtmpl": f"{out_dir}/%(title)s.%(ext)s","format": "bestvideo+bestaudio/best","merge_output_format": "mp4","noplaylist": True})
        fallback_opts = _base_ydl_opts({"outtmpl": f"{out_dir}/%(title)s.%(ext)s","format": "best","noplaylist": True})
        if cookie_file:
            video_opts["cookiefile"] = cookie_file
            fallback_opts["cookiefile"] = cookie_file
        try_opts_list = [video_opts, fallback_opts]

    # ---------- download loop ----------
    for ydl_opts in try_opts_list:
        try:
            logger.info("Trying format: %s", ydl_opts.get("format"))
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title") or "download"
                pattern = os.path.join(out_dir, f"{title}.*")
                matches = glob.glob(pattern)
                filepath = max(matches, key=os.path.getctime) if matches else ydl.prepare_filename(info)
                logger.info("Downloaded: %s", filepath)
                return {"title": title, "filepath": filepath}
        except (DownloadError, ExtractorError, Exception) as e:
            logger.warning("Attempt failed: %s", e)
            continue

    raise RuntimeError("Failed to download after all retries")