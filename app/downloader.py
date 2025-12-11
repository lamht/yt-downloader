import os
import glob
import yt_dlp
from yt_dlp.utils import DownloadError

def download_video(url: str, out_dir="downloads", audio_only=False):
    os.makedirs(out_dir, exist_ok=True)

    base_opts = {
        "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
        "noplaylist": True,
        "no_warnings": True,
        "quiet": True,
        "merge_output_format": "mp4",
    }

    # audio configuration
    if audio_only:
        base_opts.update({
            "format": "bestaudio/best",
            "postprocessors": [
                {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
            ]
        })
        try_opts = base_opts
    else:
        # try to prefer mp4 video+audio (merge), fall back to best available
        try_opts = base_opts.copy()
        try_opts["format"] = "bestvideo[ext=mp4]+bestaudio/best"

    # attempt download, with fallback if requested format isn't available
    for opts in (try_opts, base_opts):
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get("title") or "download"
                # find the produced file by title (handles postprocessor/extension changes)
                pattern = os.path.join(out_dir, f"{title}.*")
                matches = glob.glob(pattern)
                if matches:
                    filepath = max(matches, key=os.path.getctime)
                else:
                    filepath = ydl.prepare_filename(info)
                return {"title": title, "filepath": filepath}
        except DownloadError:
            # try next fallback options
            continue

    # if all attempts failed, raise to let caller handle/report the error
    raise RuntimeError("Failed to download: requested formats not available")