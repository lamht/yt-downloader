import os
import shutil
import tempfile
import glob
from app.log_config import setup_logger
import functools

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
    env_flag = os.environ.get("ENABLE_DENO", "").lower()
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
# Global dict để lưu percent trước đó
_last_percent = {}

def my_hook(d, key=None, socket=None):
    try:
        status = d.get("status")
        filename = d.get("filename", "unknown")
        
        if status == "downloading":
            downloaded = d.get("downloaded_bytes", 0)
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            percent = downloaded / total * 100 if total > 0 else 0
            percent_rounded = round(percent, 2)

            last = _last_percent.get(key, -1)
            if abs(percent_rounded - last) < 10:
                return
            _last_percent[key] = percent_rounded

            msg = f"Downloading {filename}: {percent_rounded}%"
            logger.info(msg)

            if socket and key is not None:
                socket.emit("download_status", {
                    "key": key,
                    "status": "downloading",
                    "message": msg,
                    "percent": percent_rounded
                })

        elif status == "finished":
            msg = f"Finished downloading {filename}"
            percent_rounded = 100
            logger.info(msg)
            _last_percent.pop(key, None)

            if socket and key is not None:
                socket.emit("download_status", {
                    "key": key,
                    "status": "done",
                    "message": msg,
                    "percent": percent_rounded
                })

    except Exception as e:
        logger.warning("my_hook error: %s", e)
   
class ErrorOnlyLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): logger.info("yt-dlp error: %s", msg)


def _base_ydl_opts(extra: dict | None = None):
    """
    Base yt-dlp options.
    All global logic (cookie, deno, retry, log) lives here.
    """
    opts = {
        "quiet": True,
        "logger": ErrorOnlyLogger(),
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
        opts["js_runtimes"] = {
            "deno": {}
        }
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
    key: str | None = None,
    socket=None
):
    """
    Download video or audio using yt-dlp.
    Always download fresh, no check file exist.
    """

    import functools
    os.makedirs(out_dir, exist_ok=True)

    logger.info(
        "Download called | url=%s | format_id=%s | audio_only=%s",
        url, format_id, audio_only,
    )

    try_opts_list = []

    # ---------- Build format options ----------
    if audio_only:
        formats_to_try = [
            {"format": "140"},  # m4a
            {
                "format": "251",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "aac",
                    "preferredquality": "192",
                }]
            },
            {
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "aac",
                    "preferredquality": "192",
                }]
            },
        ]
    elif format_id:
        formats_to_try = [{"format": format_id}]
    else:
        formats_to_try = [
            {"format": "bestvideo+bestaudio/best", "merge_output_format": "mp4"},
            {"format": "best"},
        ]

    # ---------- Prepare yt-dlp options ----------
    for fopt in formats_to_try:
        outtmpl = f"{out_dir}/%(title)s.%(format_id)s.%(ext)s"
        ydl_opts = _base_ydl_opts({
            "outtmpl": outtmpl,
            "noplaylist": True,
            **fopt
        })
        try_opts_list.append(ydl_opts)

    # ---------- Download loop ----------
    for ydl_opts in try_opts_list:
        try:
            logger.info("Trying format: %s", ydl_opts.get("format"))
            ydl_opts["progress_hooks"] = [functools.partial(my_hook, key=key, socket=socket)]

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title") or "download"

                if info.get("_filename"):
                    filepath = info["_filename"]
                elif info.get("requested_downloads"):
                    # fallback: lấy filepath của download đầu tiên
                    filepath = info["requested_downloads"][0].get("filepath") or ydl.prepare_filename(info)
                else:
                    filepath = ydl.prepare_filename(info)

                logger.info("Downloaded file: %s", filepath)
                return {"title": title, "filepath": filepath}

        except (DownloadError, ExtractorError, Exception) as e:
            logger.warning("Attempt failed: %s", e)
            continue

    raise RuntimeError("Failed to download after all retries")
