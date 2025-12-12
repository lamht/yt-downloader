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
        "cookiefile": "/app/app/cookies/cookies.txt",
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
    ydl_opts = _base_ydl_opts({
        "noplaylist": True,
    })
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
            logger.info("Found %d formats", len(formats))
            return {"title": title, "formats": formats, "info": info}
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("get_video_info failed: %s\n%s", e, tb)
        raise RuntimeError(f"Failed to get video info: {e}\n{tb}")

def download_video(url: str, out_dir="downloads", format_id: str | None = None, audio_only=False):
    os.makedirs(out_dir, exist_ok=True)
    logger.info("download_video called with format_id=%s, audio_only=%s", format_id, audio_only)

    if format_id:
        logger.info("User selected format_id=%s", format_id)
        ydl_opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": format_id,
            "noplaylist": True,
        })
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title") or "download"
                pattern = os.path.join(out_dir, f"{title}.*")
                matches = glob.glob(pattern)
                if matches:
                    filepath = max(matches, key=os.path.getctime)
                else:
                    filepath = ydl.prepare_filename(info)
                logger.info("Downloaded: %s", filepath)
                return {"title": title, "filepath": filepath}
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Download failed: %s\n%s", e, tb)
            raise RuntimeError(f"Failed to download: {e}")

    if audio_only:
        logger.info("Audio only mode")
        ydl_opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "bestaudio/best",
            "noplaylist": True,
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "aac", "preferredquality": "192"}
            ]
        })
        try_opts_list = [ydl_opts]
    else:
        logger.info("Video mode")
        video_opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "bestvideo+bestaudio/best",
            "noplaylist": True,
            "merge_output_format": "mp4",
        })
        fallback_opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "best",
            "noplaylist": True,
        })
        try_opts_list = [video_opts, fallback_opts]

    for ydl_opts in try_opts_list:
        try:
            logger.info("Attempting with format=%s", ydl_opts.get("format"))
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title") or "download"
                pattern = os.path.join(out_dir, f"{title}.*")
                matches = glob.glob(pattern)
                if matches:
                    filepath = max(matches, key=os.path.getctime)
                else:
                    filepath = ydl.prepare_filename(info)
                logger.info("Downloaded: %s", filepath)
                return {"title": title, "filepath": filepath}
        except Exception as e:
            logger.warning("Attempt failed: %s", e)
            continue

    raise RuntimeError("Failed to download with all attempts")