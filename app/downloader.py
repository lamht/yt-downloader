import os
import shutil
import tempfile
import glob
import logging
from flask import Flask
from flask_socketio import SocketIO
from log_config import setup_logger

import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

# ---------- Logger ----------
logger = setup_logger("downloader")
logger.info("Logger for downloader initialized")

# ---------- Cookie handling ----------
_cookie_file_path = None


def _get_cookie_file():
    """
    Read COOKIE_PATH env.
    If file exists but is read-only (e.g. /etc/secrets),
    copy to a writable temp file and reuse it.
    """
    global _cookie_file_path

    path = os.environ.get("COOKIE_PATH")
    logger.info("COOKIE_PATH env = %s", path)

    if not path:
        logger.info("COOKIE_PATH not set")
        return None

    if not os.path.isfile(path):
        logger.info("Cookie file NOT found at: %s", path)
        return None

    if _cookie_file_path:
        logger.info("Reusing temp cookie file: %s", _cookie_file_path)
        return _cookie_file_path

    try:
        tmp = tempfile.NamedTemporaryFile(
            delete=False,
            mode="w",
            encoding="utf-8",
            suffix=".txt",
        )
        tmp.close()

        shutil.copyfile(path, tmp.name)
        _cookie_file_path = tmp.name

        logger.info(
            "Cookie file copied from %s (read-only) → %s (writable)",
            path,
            _cookie_file_path,
        )
        return _cookie_file_path

    except Exception as e:
        logger.info("Failed to prepare temp cookie file: %s", e)
        return None


# ---------- Deno (JS runtime) ----------
def _enable_deno() -> bool:
    """
    Enable Deno JS runtime if:
    - ENV DENO is truthy
    - deno binary exists in PATH
    """
    env_flag = os.environ.get("DENO", "").lower()
    if env_flag not in ("1", "true", "yes", "on"):
        logger.info("DENO env disabled or not set")
        return False

    from shutil import which
    if which("deno") is None:
        logger.info("DENO env enabled but deno binary not found")
        return False

    logger.info("DENO JS runtime detected and enabled")
    return True


# ---------- yt-dlp utils ----------
def my_hook(d):
    logger.info("Progress: %s", d)


def _base_ydl_opts(extra: dict | None = None):
    """
    Base yt-dlp options.
    All global logic (cookie, deno, retry, log) lives here.
    """
    opts = {
        "quiet": True,
        "progress_hooks": [my_hook],
        "logger": logger,
        "no_warnings": False,
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

    # ---------- JS runtime ----------
    if _enable_deno():
        opts["js_runtimes"] = ["deno"]
        logger.info("yt-dlp js_runtimes = deno")

    # ---------- Cookie ----------
    cookie_file = _get_cookie_file()
    if cookie_file:
        opts["cookiefile"] = cookie_file
        logger.info("yt-dlp cookie enabled: %s", cookie_file)
    else:
        logger.info("yt-dlp cookie disabled")

    if extra:
        opts.update(extra)

    return opts


# ---------- Public APIs ----------
def get_video_info(url: str):
    logger.info("Inspecting URL: %s", url)

    ydl_opts = _base_ydl_opts({"noplaylist": True})

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
            return {
                "title": title,
                "formats": formats,
                "info": info,
            }

    except Exception as e:
        logger.exception("get_video_info failed for URL: %s", url)
        raise RuntimeError(f"Failed to get video info: {e}")


def download_video(
    url: str,
    out_dir: str = "downloads",
    format_id: str | None = None,
    audio_only: bool = False,
):
    os.makedirs(out_dir, exist_ok=True)

    logger.info(
        "Download called | url=%s | format_id=%s | audio_only=%s",
        url,
        format_id,
        audio_only,
    )

    try_opts_list = []

    if format_id:
        try_opts_list.append(
            _base_ydl_opts({
                "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
                "format": format_id,
                "noplaylist": True,
            })
        )

    elif audio_only:
        try_opts_list.append(
            _base_ydl_opts({
                "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
                "format": "bestaudio/best",
                "noplaylist": True,
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "aac",
                    "preferredquality": "192",
                }],
            })
        )

    else:
        try_opts_list.extend([
            _base_ydl_opts({
                "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
                "noplaylist": True,
            }),
            _base_ydl_opts({
                "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
                "format": "best",
                "noplaylist": True,
            }),
        ])

    # ---------- Download loop ----------
    for ydl_opts in try_opts_list:
        try:
            logger.info("Trying format: %s", ydl_opts.get("format"))

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title") or "download"

                pattern = os.path.join(out_dir, f"{title}.*")
                matches = glob.glob(pattern)

                filepath = (
                    max(matches, key=os.path.getctime)
                    if matches
                    else ydl.prepare_filename(info)
                )

                logger.info("Downloaded file: %s", filepath)
                return {"title": title, "filepath": filepath}

        except (DownloadError, ExtractorError, Exception) as e:
            logger.warning("Attempt failed: %s", e)
            continue

    raise RuntimeError("Failed to download after all retries")
