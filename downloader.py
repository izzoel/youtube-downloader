import os
import re
import asyncio
from typing import Dict, Any, List, Optional
from urllib.parse import urlparse, parse_qs
from playwright.async_api import async_playwright
import yt_dlp

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
COOKIES_FILE = os.path.join(BASE_DIR, "cookies.txt")
PLAYWRIGHT_COOKIES_FILE = os.path.join(BASE_DIR, "downloads", "cookies_playwright.txt")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

def get_active_cookie_file() -> Optional[str]:
    """Mengembalikan path cookiefile jika cookies.txt atau cookies_playwright.txt tersedia."""
    if os.path.exists(COOKIES_FILE) and os.path.getsize(COOKIES_FILE) > 0:
        return COOKIES_FILE
    if os.path.exists(PLAYWRIGHT_COOKIES_FILE) and os.path.getsize(PLAYWRIGHT_COOKIES_FILE) > 0:
        return PLAYWRIGHT_COOKIES_FILE
    return None

def save_playwright_cookies(cookies: list, filepath: str) -> None:
    """Menyimpan cookies dari Playwright ke format Netscape cookies untuk digunakan yt-dlp."""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n")
            for c in cookies:
                domain = c.get("domain", "")
                flag = "TRUE" if domain.startswith(".") else "FALSE"
                path = c.get("path", "/")
                secure = "TRUE" if c.get("secure", False) else "FALSE"
                expires = int(c.get("expires", -1))
                if expires <= 0:
                    expires = 2147483647
                name = c.get("name", "")
                value = c.get("value", "")
                f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expires}\t{name}\t{value}\n")
    except Exception as e:
        print(f"Warning: Gagal menyimpan cookies Playwright: {e}")

def format_duration(seconds: Optional[int]) -> str:
    """Mengubah durasi detik menjadi format HH:MM:SS atau MM:SS."""
    if not seconds:
        return "00:00"
    m, s = divmod(seconds, 60)
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

async def verify_youtube_with_playwright(url: str) -> Dict[str, Any]:
    """
    Menggunakan Playwright async untuk:
    1. Membuka URL YouTube secara headless.
    2. Mendeteksi apakah video ada / diblokir / dibatasi umur / tidak tersedia.
    3. Mengambil User-Agent dan cookies halaman bila ada bot-check atau consent popup.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )
        context = await browser.new_context(
            user_agent=DEFAULT_USER_AGENT,
            viewport={"width": 1280, "height": 720},
            locale="id-ID",
            extra_http_headers={"Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7"}
        )
        page = await context.new_page()

        try:
            # Buka halaman video YouTube
            response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            status_code = response.status if response else 200

            if status_code >= 400:
                raise Exception(f"Halaman YouTube mengembalikan kode status HTTP {status_code}")

            # Tunggu elemen utama YouTube muncul
            await page.wait_for_timeout(2000)

            # Cek penanda error YouTube jika ada (misal video dihapus / private)
            error_elements = await page.query_selector_all(
                "yt-playability-error-supported-renderers, #error-screen, ytd-player-error-message-renderer"
            )
            error_text = None
            for elem in error_elements:
                text = await elem.inner_text()
                if text and ("Video unavailable" in text or "Video tidak tersedia" in text or "Private video" in text):
                    error_text = text.strip()
                    break

            if error_text:
                raise Exception(f"YouTube Playability Error: {error_text}")

            # Ambil judul awal dari DOM sebagai konfirmasi
            title = await page.title()
            title = re.sub(r"\s*-\s*YouTube$", "", title)

            # Ekstrak cookies yang didapat dari sesi browser
            cookies = await context.cookies()

            return {
                "valid": True,
                "page_title": title,
                "cookies": cookies,
                "user_agent": DEFAULT_USER_AGENT
            }

        finally:
            await browser.close()


def _extract_ytdlp_info(url: str, cookie_file: Optional[str] = None) -> dict:
    """Fungsi pembantu sync untuk yt-dlp extract_info."""
    cookie = cookie_file or get_active_cookie_file()
    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": False,
        "user_agent": DEFAULT_USER_AGENT,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb", "web"],
            }
        },
    }
    if cookie:
        ydl_opts["cookiefile"] = cookie

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)


async def get_video_details(url: str) -> Dict[str, Any]:
    """
    Kombinasi Playwright Async & yt-dlp:
    1. Coba ekstraksi cepat langsung via yt-dlp dengan client mobile/web bypass.
    2. Jika dibatasi/gagal, jalankan Playwright untuk verifikasi status halaman & ambil session cookies.
    """
    if not is_valid_youtube_url(url):
        raise ValueError("URL yang diberikan bukan tautan YouTube yang valid.")

    info = None
    last_error = None

    # 1. Coba ekstraksi cepat via yt-dlp
    try:
        info = await asyncio.to_thread(_extract_ytdlp_info, url)
    except Exception as e:
        last_error = e

    # 2. Jika yt-dlp awal gagal, gunakan Playwright untuk bypass & ekstrak session cookies
    if not info:
        try:
            playwright_result = await verify_youtube_with_playwright(url)
            if playwright_result.get("cookies"):
                save_playwright_cookies(playwright_result["cookies"], PLAYWRIGHT_COOKIES_FILE)
            # Ulangi ekstraksi dengan cookies Playwright
            info = await asyncio.to_thread(_extract_ytdlp_info, url, PLAYWRIGHT_COOKIES_FILE)
        except Exception as pe:
            err_msg = str(last_error) if last_error else str(pe)
            if "not available" in err_msg.lower():
                raise Exception(
                    "Video tidak dapat diakses atau diblokir oleh YouTube untuk IP server ini. "
                    "Solusi: Perbarui yt-dlp di server (`pip install -U yt-dlp`) atau letakkan file `cookies.txt` di folder project."
                )
            raise Exception(f"Gagal memeriksa video: {err_msg}")

    if not info:
        raise Exception("Gagal mengekstrak metadata dari video YouTube.")

    formats = info.get("formats", [])
    available_heights = set()
    for f in formats:
        h = f.get("height")
        vcodec = f.get("vcodec")
        if h and vcodec and vcodec != "none":
            available_heights.add(h)

    # Format pilihan resolusi yang ramah pengguna
    standard_resolutions = [
        {"height": 1080, "label": "1080p Full HD", "ext": "mp4"},
        {"height": 720, "label": "720p HD", "ext": "mp4"},
        {"height": 480, "label": "480p SD", "ext": "mp4"},
        {"height": 360, "label": "360p Hemat Data", "ext": "mp4"},
    ]

    available_options = []
    # Tambahkan resolusi video yang ada
    for opt in standard_resolutions:
        h = opt["height"]
        # Jika resolusi tersedia di video atau video memiliki resolusi lebih tinggi
        if any(ah >= h for ah in available_heights) or not available_heights:
            available_options.append({
                "id": f"video_{h}",
                "type": "video",
                "label": f"Video {opt['label']}",
                "resolution": f"{h}p",
                "ext": "mp4",
                "format_spec": f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
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
    """Proses sinkronus download yt-dlp yang dijalankan di background thread."""
    os.makedirs(download_dir, exist_ok=True)

    # Pola nama file yang bersih dan aman
    outtmpl = os.path.join(download_dir, "%(title).120B [%(id)s].%(ext)s")
    cookie = get_active_cookie_file()

    ydl_opts: Dict[str, Any] = {
        "outtmpl": outtmpl,
        "format": format_spec,
        "quiet": True,
        "no_warnings": True,
        "user_agent": DEFAULT_USER_AGENT,
        "merge_output_format": "mp4" if not is_audio else None,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "ios", "mweb", "web"],
            }
        },
    }
    if cookie:
        ydl_opts["cookiefile"] = cookie

    if is_audio:
        ydl_opts["postprocessors"] = [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }]

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(result)
        
        # Jika konversi audio ke mp3, ekstensi file berubah jadi .mp3
        if is_audio:
            base, _ = os.path.splitext(filename)
            filename = base + ".mp3"

        if not os.path.exists(filename):
            # Coba cari file yang cocok di direktori
            basename = os.path.splitext(os.path.basename(filename))[0]
            for f in os.listdir(download_dir):
                if f.startswith(basename):
                    filename = os.path.join(download_dir, f)
                    break

        filesize = os.path.getsize(filename) if os.path.exists(filename) else 0

        return {
            "success": True,
            "filename": os.path.basename(filename),
            "full_path": filename,
            "filesize_mb": round(filesize / (1024 * 1024), 2),
            "title": result.get("title", "Video")
        }


async def download_video(url: str, format_id: str, download_dir: str) -> Dict[str, Any]:
    """
    Memulai download video YouTube secara non-blocking dengan format yang dipilih.
    """
    if not is_valid_youtube_url(url):
        raise ValueError("URL YouTube tidak valid.")

    is_audio = (format_id == "audio_mp3")

    # Tentukan format_spec berdasarkan format_id
    if is_audio:
        format_spec = "bestaudio/best"
    elif format_id.startswith("video_"):
        try:
            h = int(format_id.replace("video_", ""))
        except ValueError:
            h = 720
        format_spec = f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"
    else:
        format_spec = "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"

    # Jalankan download di async thread pool
    download_result = await asyncio.to_thread(
        _download_ytdlp_task,
        url=url,
        format_spec=format_spec,
        is_audio=is_audio,
        download_dir=download_dir
    )

    return download_result
