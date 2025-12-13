import os
import glob
import yt_dlp
import logging
import traceback
from yt_dlp.utils import DownloadError, ExtractorError

logger = logging.getLogger("yt_downloader")
logger.setLevel(logging.INFO)


WINDOWS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def _base_ydl_opts(extra: dict | None = None):
    opts = {
        "quiet": False,
        "no_warnings": False,
        "logger": logger,

        # ===== USER AGENT WINDOWS =====
        "user_agent": WINDOWS_UA,

        # ===== RETRY CONFIG =====
        "retries": 3,
        "fragment_retries": 3,
        "extractor_retries": 3,

        # sleep: 2s, 4s, 6s
        "retry_sleep_functions": {
            "http": lambda n: 2 * n,
            "fragment": lambda n: 2 * n,
            "extractor": lambda n: 2 * n,
        },

        # ===== NETWORK HARDEN =====
        "socket_timeout": 30,
        "nocheckcertificate": True,
        "geo_bypass": True,
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
            return {
                "title": title,
                "formats": formats,
                "info": info,
            }

    except Exception as e:
        tb = traceback.format_exc()
        logger.error("get_video_info failed: %s\n%s", e, tb)
        raise RuntimeError(f"Failed to get video info: {e}\n{tb}")


def download_video(
    url: str,
    out_dir: str = "downloads",
    format_id: str | None = None,
    audio_only: bool = False,
):
    os.makedirs(out_dir, exist_ok=True)
    logger.info(
        "download_video called format_id=%s audio_only=%s",
        format_id,
        audio_only,
    )

    # ================= FORMAT ID =================
    if format_id:
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
                filepath = (
                    max(matches, key=os.path.getctime)
                    if matches
                    else ydl.prepare_filename(info)
                )

                logger.info("Downloaded: %s", filepath)
                return {"title": title, "filepath": filepath}

        except Exception as e:
            tb = traceback.format_exc()
            logger.error("Download failed: %s\n%s", e, tb)
            raise RuntimeError(f"Failed to download: {e}\n{tb}")

    # ================= AUDIO ONLY =================
    if audio_only:
        ydl_opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "bestaudio/best",
            "noplaylist": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "aac",
                    "preferredquality": "192",
                }
            ],
        })
        try_opts_list = [ydl_opts]

    # ================= VIDEO =================
    else:
        video_opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "bestvideo+bestaudio/best",
            "merge_output_format": "mp4",
            "noplaylist": True,
        })

        fallback_opts = _base_ydl_opts({
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "best",
            "noplaylist": True,
        })

        try_opts_list = [video_opts, fallback_opts]

    # ================= DOWNLOAD LOOP =================
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

                logger.info("Downloaded: %s", filepath)
                return {"title": title, "filepath": filepath}

        except (DownloadError, ExtractorError, Exception) as e:
            logger.warning("Attempt failed: %s", e)
            continue

    raise RuntimeError("Failed to download after all retries")