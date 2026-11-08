import os
import urllib.parse
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl

from downloader import get_video_details, download_video, is_valid_youtube_url

# Setup paths
BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
DOWNLOADS_DIR = BASE_DIR / "downloads"

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="YouTube Video & Audio Downloader",
    description="Web App FastAPI + Playwright + yt-dlp untuk mengunduh video YouTube.",
    version="1.0.0"
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


class InfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str
    format_id: str


@app.get("/", response_class=HTMLResponse)
async def index_page(request: Request):
    """Menampilkan halaman utama UI Downloader."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/info")
async def fetch_info(req: InfoRequest):
    """
    Mengambil informasi video YouTube (judul, thumbnail, durasi, opsi kualitas)
    menggunakan Playwright Async & yt-dlp.
    """
    clean_url = req.url.strip()
    if not is_valid_youtube_url(clean_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tautan yang dimasukkan bukan URL YouTube yang valid."
        )

    try:
        data = await get_video_details(clean_url)
        return JSONResponse(content={"success": True, "data": data})
    except ValueError as ve:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(ve))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Terjadi kesalahan saat memeriksa video: {str(e)}"
        )


@app.post("/api/download")
async def start_download(req: DownloadRequest):
    """
    Memulai proses pengunduhan video/audio berdasarkan format yang dipilih.
    Menyimpan file ke folder 'downloads/' dan mengembalikan link download langsung.
    """
    clean_url = req.url.strip()
    format_id = req.format_id.strip()

    if not is_valid_youtube_url(clean_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL YouTube tidak valid."
        )

    try:
        result = await download_video(
            url=clean_url,
            format_id=format_id,
            download_dir=str(DOWNLOADS_DIR)
        )

        encoded_filename = urllib.parse.quote(result["filename"])
        file_download_url = f"/api/file/{encoded_filename}"

        return JSONResponse(content={
            "success": True,
            "message": "Pengunduhan berhasil diselesaikan!",
            "filename": result["filename"],
            "filesize_mb": result["filesize_mb"],
            "download_url": file_download_url
        })

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Gagal mengunduh video: {str(e)}"
        )


@app.get("/api/file/{filename}")
async def get_downloaded_file(filename: str):
    """
    Menyajikan file hasil unduhan langsung ke browser pengguna (Attachment Download).
    """
    # Mencegah path traversal attacks
    safe_filename = os.path.basename(filename)
    file_path = DOWNLOADS_DIR / safe_filename

    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File unduhan tidak ditemukan di server."
        )

    return FileResponse(
        path=file_path,
        filename=safe_filename,
        media_type="application/octet-stream"
    )


@app.get("/api/downloads")
async def list_downloads():
    """
    Menampilkan daftar file yang sudah pernah diunduh dan tersimpan di folder downloads/.
    """
    files = []
    if DOWNLOADS_DIR.exists():
        for file in sorted(DOWNLOADS_DIR.iterdir(), key=os.path.getmtime, reverse=True):
            if file.is_file() and not file.name.startswith("."):
                size_mb = round(file.stat().st_size / (1024 * 1024), 2)
                encoded_name = urllib.parse.quote(file.name)
                files.append({
                    "name": file.name,
                    "size_mb": size_mb,
                    "download_url": f"/api/file/{encoded_name}"
                })
    return {"success": True, "files": files}


@app.delete("/api/file/{filename}")
async def delete_downloaded_file(filename: str):
    """
    Menghapus file tertentu dari folder downloads/.
    """
    safe_filename = os.path.basename(filename)
    file_path = DOWNLOADS_DIR / safe_filename

    if file_path.exists() and file_path.is_file():
        try:
            file_path.unlink()
            return {"success": True, "message": f"File '{safe_filename}' berhasil dihapus."}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Gagal menghapus file: {str(e)}"
            )

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File tidak ditemukan.")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
