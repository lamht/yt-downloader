import os
import glob
import yt_dlp
from yt_dlp.utils import DownloadError, ExtractorError

def get_video_info(url: str):
    """
    Return video meta and available formats without downloading.
    """
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
    }
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

def download_video(url: str, out_dir="downloads", format_id: str | None = None, audio_only=False):
    os.makedirs(out_dir, exist_ok=True)

    base_opts = {
        "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
        "noplaylist": True,
        "no_warnings": True,
        "quiet": True,
        "merge_output_format": "mp4",
    }

    if audio_only:
        base_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ]
        })
        try_opts = base_opts
    else:
        try_opts = base_opts.copy()
        # prefer mp4+audio merged, otherwise best available
        try_opts["format"] = "bestvideo[ext=mp4]+bestaudio/best"

    # if user specified explicit format id, use it as highest priority
    if format_id:
        user_opts = base_opts.copy()
        user_opts["format"] = format_id
        opts_sequence = (user_opts, try_opts, base_opts)
    else:
        opts_sequence = (try_opts, base_opts)

    for opts in opts_sequence:
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title") or "download"
                pattern = os.path.join(out_dir, f"{title}.*")
                matches = glob.glob(pattern)
                if matches:
                    filepath = max(matches, key=os.path.getctime)
                else:
                    # prepare_filename may include path based on outtmpl
                    filepath = ydl.prepare_filename(info)
                return {"title": title, "filepath": filepath}
        except (DownloadError, ExtractorError):
            continue

    raise RuntimeError("Failed to download: requested formats not available")