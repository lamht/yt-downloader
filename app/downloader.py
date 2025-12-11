import yt_dlp

def download_video(url: str, out_dir="downloads", audio_only=False):
    if audio_only:
        ydl_opts = {
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "bestaudio/best",
        }
    else:
        ydl_opts = {
            "outtmpl": f"{out_dir}/%(title)s.%(ext)s",
            "format": "best[ext=mp4]/best",
        }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return {
            "title": info.get("title"),
            "filepath": ydl.prepare_filename(info)
        }