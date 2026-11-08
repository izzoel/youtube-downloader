import os
import re
import asyncio
from pathlib import Path
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse
import yt_dlp

BASE_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
COOKIES_FILE = BASE_DIR / "cookies.txt"

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)


def format_duration(seconds: Optional[int]) -> str:
    """Mengubah durasi detik menjadi format HH:MM:SS atau MM:SS."""
    if not seconds:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def is_valid_youtube_url(url: str) -> bool:
    """Memvalidasi apakah URL merupakan tautan YouTube yang valid."""
    if not url or not isinstance(url, str):
        return False
    parsed = urlparse(url.strip())
    domain = parsed.netloc.lower()
    if domain in ("www.youtube.com", "youtube.com", "m.youtube.com"):
        return bool("/watch" in parsed.path or "/shorts/" in parsed.path or "/embed/" in parsed.path)
    if domain in ("youtu.be", "www.youtu.be"):
        return len(parsed.path.strip("/")) > 0
    return False


def get_base_ydl_opts() -> Dict[str, Any]:
    """Opsi dasar untuk yt-dlp."""
    opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
    }
    if COOKIES_FILE.exists() and COOKIES_FILE.stat().st_size > 0:
        opts["cookiefile"] = str(COOKIES_FILE)
    return opts


def _extract_ytdlp_info(url: str) -> dict:
    """Ekstraksi metadata video langsung via yt-dlp (persis seperti CLI)."""
    opts = get_base_ydl_opts()
    opts.update({
        "skip_download": True,
        "extract_flat": False,
    })
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


async def get_video_details(url: str) -> Dict[str, Any]:
    """
    Mengambil informasi video YouTube (judul, thumbnail, durasi, opsi kualitas)
    menggunakan yt-dlp murni secara non-blocking.
    """
    if not is_valid_youtube_url(url):
        raise ValueError("URL yang diberikan bukan tautan YouTube yang valid.")

    print(f"\n[yt-dlp] Mengekstrak informasi video: {url}")
    info = await asyncio.to_thread(_extract_ytdlp_info, url)
    if not info:
        raise Exception("Gagal mengekstrak metadata dari video YouTube.")

    formats = info.get("formats", [])
    available_heights = set()
    for f in formats:
        h = f.get("height")
        vcodec = f.get("vcodec")
        if h and vcodec and vcodec != "none":
            available_heights.add(h)

    available_options = [
        {
            "id": "best_quality",
            "type": "video",
            "label": "Kualitas Terbaik Otomatis (Rekomendasi)",
            "resolution": "Terbaik",
            "ext": "mp4",
            "format_spec": "bestvideo+bestaudio/best"
        }
    ]

    standard_resolutions = [
        {"height": 1080, "label": "1080p Full HD", "ext": "mp4"},
        {"height": 720, "label": "720p HD", "ext": "mp4"},
        {"height": 480, "label": "480p SD", "ext": "mp4"},
        {"height": 360, "label": "360p Hemat Data", "ext": "mp4"},
    ]

    for opt in standard_resolutions:
        h = opt["height"]
        if any(ah >= h for ah in available_heights) or not available_heights:
            available_options.append({
                "id": f"video_{h}",
                "type": "video",
                "label": f"Video {opt['label']}",
                "resolution": f"{h}p",
                "ext": "mp4",
                "format_spec": f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
            })

    # Opsi khusus Audio MP3
    available_options.append({
        "id": "audio_mp3",
        "type": "audio",
        "label": "Audio Saja (MP3 High Quality 192kbps)",
        "resolution": "Audio",
        "ext": "mp3",
        "format_spec": "bestaudio/best"
    })

    return {
        "id": info.get("id"),
        "title": info.get("title") or "Video YouTube",
        "duration": info.get("duration", 0),
        "duration_formatted": format_duration(info.get("duration")),
        "thumbnail": info.get("thumbnail"),
        "channel": info.get("uploader") or info.get("channel") or "Unknown Channel",
        "views": info.get("view_count", 0),
        "options": available_options
    }


def _download_ytdlp_task(url: str, format_spec: str, is_audio: bool, download_dir: str) -> dict:
    """Proses download yt-dlp secara sinkronus di background thread."""
    os.makedirs(download_dir, exist_ok=True)
    outtmpl = os.path.join(download_dir, "%(title).120B [%(id)s].%(ext)s")

    opts = get_base_ydl_opts()
    opts.update({
        "outtmpl": outtmpl,
        "format": format_spec,
        "merge_output_format": "mp4" if not is_audio else None,
        "retries": 5,
        "fragment_retries": 5,
    })

    if is_audio:
        opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    print(f"\n[yt-dlp] Memulai pengunduhan: {url} (Format: {format_spec})")
    with yt_dlp.YoutubeDL(opts) as ydl:
        result = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(result)

        if is_audio:
            base, _ = os.path.splitext(filename)
            filename = base + ".mp3"
        elif not filename.endswith(".mp4") and os.path.exists(os.path.splitext(filename)[0] + ".mp4"):
            filename = os.path.splitext(filename)[0] + ".mp4"

        if not os.path.exists(filename):
            basename = os.path.splitext(os.path.basename(filename))[0]
            for f in os.listdir(download_dir):
                if f.startswith(basename):
                    filename = os.path.join(download_dir, f)
                    break

        filesize = os.path.getsize(filename) if os.path.exists(filename) else 0
        print(f"[yt-dlp] Selesai diunduh: {os.path.basename(filename)} ({round(filesize / (1024 * 1024), 2)} MB)\n")

        return {
            "success": True,
            "filename": os.path.basename(filename),
            "full_path": filename,
            "filesize_mb": round(filesize / (1024 * 1024), 2),
            "title": result.get("title", "Video")
        }


async def download_video(url: str, format_id: str, download_dir: str) -> Dict[str, Any]:
    """
    Memulai download video YouTube secara non-blocking dengan format yang dipilih pengguna.
    """
    if not is_valid_youtube_url(url):
        raise ValueError("URL YouTube tidak valid.")

    is_audio = (format_id == "audio_mp3")

    if is_audio:
        format_spec = "bestaudio/best"
    elif format_id == "best_quality":
        format_spec = "bestvideo+bestaudio/best"
    elif format_id.startswith("video_"):
        try:
            h = int(format_id.replace("video_", ""))
        except ValueError:
            h = 720
        format_spec = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
    else:
        format_spec = "bestvideo+bestaudio/best"

    download_result = await asyncio.to_thread(
        _download_ytdlp_task,
        url=url,
        format_spec=format_spec,
        is_audio=is_audio,
        download_dir=download_dir
    )

    return download_result
