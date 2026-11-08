import os
import json
import uuid
import asyncio
import urllib.parse
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl

from downloader import (
    get_video_details, 
    download_video, 
    is_valid_youtube_url, 
    sanitize_youtube_url,
    init_download_task, 
    get_task_status,
    DOWNLOAD_TASKS
)

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
@app.get("/index.html", response_class=HTMLResponse)
async def index_page(request: Request):
    """Menampilkan halaman utama UI Downloader."""
    return templates.TemplateResponse(request=request, name="index.html")


@app.post("/api/info")
async def fetch_info(req: InfoRequest):
    """
    Mengambil informasi video YouTube (judul, thumbnail, durasi, opsi kualitas)
    menggunakan yt-dlp.
    """
    clean_url = sanitize_youtube_url(req.url.strip())
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
    Memulai proses pengunduhan video/audio di background dan mengembalikan task_id
    agar progress real-time dapat dipantau dari antarmuka pengguna.
    """
    clean_url = sanitize_youtube_url(req.url.strip())
    format_id = req.format_id.strip()

    if not is_valid_youtube_url(clean_url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="URL YouTube tidak valid."
        )

    task_id = uuid.uuid4().hex[:12]
    init_download_task(task_id, clean_url)

    async def run_download_job():
        try:
            result = await download_video(
                url=clean_url,
                format_id=format_id,
                download_dir=str(DOWNLOADS_DIR),
                task_id=task_id
            )
            encoded_filename = urllib.parse.quote(result["filename"])
            if task_id in DOWNLOAD_TASKS:
                DOWNLOAD_TASKS[task_id]["download_url"] = f"/api/file/{encoded_filename}"
        except Exception as e:
            if task_id in DOWNLOAD_TASKS:
                DOWNLOAD_TASKS[task_id].update({
                    "status": "error",
                    "error": str(e),
                    "message": f"Gagal mengunduh: {str(e)}"
                })

    asyncio.create_task(run_download_job())

    return JSONResponse(content={
        "success": True,
        "task_id": task_id,
        "message": "Pengunduhan telah dimulai."
    })


@app.get("/api/download/stream/{task_id}")
async def stream_download_progress(task_id: str):
    """
    Server-Sent Events (SSE) endpoint untuk streaming progress pengunduhan secara real-time.
    """
    async def event_generator():
        while True:
            task = get_task_status(task_id)
            if not task:
                yield f"data: {json.dumps({'status': 'not_found'})}\n\n"
                break

            yield f"data: {json.dumps(task)}\n\n"

            if task.get("status") in ("completed", "error"):
                break

            await asyncio.sleep(0.3)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.get("/api/download/status/{task_id}")
async def get_download_status(task_id: str):
    """
    Polling fallback endpoint untuk memeriksa status pengunduhan.
    """
    task = get_task_status(task_id)
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task tidak ditemukan.")
    return JSONResponse(content=task)


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
