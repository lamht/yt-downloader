import os
import glob
import yt_dlp
import logging
import traceback
from yt_dlp.utils import DownloadError, ExtractorError

logger = logging.getLogger("yt_downloader")
logger.setLevel(logging.INFO)

def _base_ydl_opts(extra: dict | None = None):
    opts = {
        "quiet": False,
        "no_warnings": False,
        "logger": logger,
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

    base_opts = {
        "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
        "noplaylist": True,
        "no_warnings": False,
        "quiet": False,
        "merge_output_format": "mp4",
    }

    # If user selected a specific format_id, use ONLY that (don't fallback)
    if format_id:
        logger.info("User selected specific format_id=%s", format_id)
        opts = base_opts.copy()
        opts["format"] = format_id
        full_opts = _base_ydl_opts(extra=opts)
        try:
            logger.info("Attempting download with format_id=%s", format_id)
            with yt_dlp.YoutubeDL(full_opts) as ydl:
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
            tb = traceback.format_exc()
            logger.error("Download with format_id=%s failed: %s\n%s", format_id, e, tb)
            raise RuntimeError(f"Failed to download format {format_id}: {e}")

    # No format_id selected - use audio_only or fallback logic
    if audio_only:
        logger.info("Audio only mode")
        base_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ]
        })
        try_opts = base_opts
    else:
        logger.info("Video mode - trying best video+audio")
        try_opts = base_opts.copy()
        try_opts["format"] = "bestvideo[ext=mp4]+bestaudio/best"

    opts_sequence = (try_opts, base_opts)
    last_err = None

    for opts in opts_sequence:
        full_opts = _base_ydl_opts(extra=opts)
        try:
            logger.info("Attempting download with opts format=%s", opts.get("format"))
            with yt_dlp.YoutubeDL(full_opts) as ydl:
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
            tb = traceback.format_exc()
            logger.warning("Download attempt failed: %s\n%s", e, tb)
            last_err = f"{e}\n{tb}"
            continue

    raise RuntimeError("Failed to download: requested formats not available\n" + (last_err or ""))