import os
import glob
import yt_dlp
import logging
import traceback
import time
from yt_dlp.utils import DownloadError, ExtractorError

logger = logging.getLogger("yt_downloader")
logger.setLevel(logging.INFO)

def _base_ydl_opts(extra: dict | None = None):
    opts = {
        "quiet": False,
        "no_warnings": False,
        "logger": logger,
        "forceipv4": True,
        "socket_timeout": 30,
        "retries": {"main": 10, "fragment": 10},
        "fragment_retries": 10,
        "skip_unavailable_fragments": True,
        "http_headers": {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1"
        },
        "extractor_args": {
            "youtube": {
                "player_client": ["android"],
                "player_skip": ["js", "configs"],
            }
        },
        "cookiefile": None,  # will use default browser cookies if available
    }
    if extra:
        opts.update(extra)
    return opts

def get_video_info(url: str):
    """
    Return video meta and available formats without downloading.
    """
    ydl_opts = _base_ydl_opts({"skip_download": True})
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
            return {"title": title, "formats": formats, "info": info}
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("get_video_info failed: %s\n%s", e, tb)
        raise RuntimeError(f"Failed to get video info: {e}\n{tb}")

def download_video(url: str, out_dir="downloads", format_id: str | None = None, audio_only=False):
    os.makedirs(out_dir, exist_ok=True)
    logger.info("download_video called with format_id=%s, audio_only=%s", format_id, audio_only)

    # If user selected a specific format_id, use ONLY that
    if format_id:
        logger.info("User selected specific format_id=%s", format_id)
        ydl_opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": format_id,
            "noplaylist": True,
            "no_warnings": False,
            "quiet": False,
        })
        
        # retry loop for 403 errors
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info("Attempting download with format_id=%s (attempt %d/%d)", format_id, attempt+1, max_retries)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    title = info.get("title") or "download"
                    pattern = os.path.join(out_dir, f"{title}.*")
                    matches = glob.glob(pattern)
                    if matches:
                        filepath = max(matches, key=os.path.getctime)
                    else:
                        filepath = ydl.prepare_filename(info)
                    logger.info("Downloaded file: %s", filepath)
                    return {"title": title, "filepath": filepath}
            except Exception as e:
                if "403" in str(e) and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5  # exponential backoff: 5s, 10s, 15s
                    logger.warning("Got 403, retrying in %ds...", wait_time)
                    time.sleep(wait_time)
                    continue
                tb = traceback.format_exc()
                logger.error("Download with format_id=%s failed: %s\n%s", format_id, e, tb)
                raise RuntimeError(f"Failed to download format {format_id}: {e}")

    # No format_id selected - use audio_only or fallback logic
    if audio_only:
        logger.info("Audio only mode")
        ydl_opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "bestaudio/best",
            "noplaylist": True,
            "no_warnings": False,
            "quiet": False,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ]
        })
        try_opts_list = [ydl_opts]
    else:
        logger.info("Video mode - trying best video+audio")
        video_opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "bestvideo[ext=mp4]+bestaudio/best",
            "noplaylist": True,
            "no_warnings": False,
            "quiet": False,
            "merge_output_format": "mp4",
        })
        fallback_opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "best",
            "noplaylist": True,
            "no_warnings": False,
            "quiet": False,
        })
        try_opts_list = [video_opts, fallback_opts]

    last_err = None
    for ydl_opts in try_opts_list:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                logger.info("Attempting download with format=%s (attempt %d/%d)", ydl_opts.get("format"), attempt+1, max_retries)
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    title = info.get("title") or "download"
                    pattern = os.path.join(out_dir, f"{title}.*")
                    matches = glob.glob(pattern)
                    if matches:
                        filepath = max(matches, key=os.path.getctime)
                    else:
                        filepath = ydl.prepare_filename(info)
                    logger.info("Downloaded file: %s", filepath)
                    return {"title": title, "filepath": filepath}
            except (DownloadError, ExtractorError, Exception) as e:
                if "403" in str(e) and attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5
                    logger.warning("Got 403, retrying in %ds...", wait_time)
                    time.sleep(wait_time)
                    continue
                tb = traceback.format_exc()
                logger.warning("Download attempt failed: %s\n%s", e, tb)
                last_err = f"{e}\n{tb}"
                break  # move to next format option

    raise RuntimeError("Failed to download: requested formats not available\n" + (last_err or ""))