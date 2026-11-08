# YouTube Video & Audio Downloader (FastAPI + Playwright + yt-dlp)

Aplikasi web modern berbasis Python **FastAPI**, **Playwright (Async API)**, dan **yt-dlp** untuk mengunduh video dan audio YouTube dengan antarmuka web interaktif menggunakan Tailwind CSS.

---

## 📁 Struktur Direktori

```text
youtube-downloader/
├── main.py              # Server FastAPI, routing endpoint API, dan static handler
├── downloader.py        # Modul Playwright Async (verifikasi) & yt-dlp (ekstraksi & unduh)
├── requirements.txt     # Daftar dependensi Python
├── templates/
│   └── index.html       # Antarmuka Web responsif (Tailwind CSS)
└── downloads/           # Direktori penyimpanan file video/audio hasil unduhan
```

---

## 🚀 Panduan Setup & Menjalankan di macOS

### 1. Masuk ke Direktori Project
Buka Terminal macOS dan navigasikan ke direktori project:
```bash
cd "/Applications/MAMP/htdocs/#python/youtube-downloader"
```

### 2. Buat & Aktifkan Virtual Environment (Direkomendasikan)
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install Dependensi
```bash
pip install -r requirements.txt
```

### 4. Install Browser Binary Playwright (Chromium)
Playwright membutuhkan binary browser Chromium untuk pertama kali:
```bash
playwright install chromium
```

> **Catatan FFmpeg**: yt-dlp membutuhkan `ffmpeg` untuk menggabungkan video beresolusi tinggi (1080p+) dan konversi audio MP3. Di Mac, Anda dapat memasangnya lewat Homebrew jika belum ada:
> ```bash
> brew install ffmpeg
> ```

### 5. Jalankan Server Uvicorn
Jalankan server aplikasi dengan auto-reload:
```bash
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```
Atau cukup:
```bash
python3 main.py
```

### 6. Akses Aplikasi di Browser
Buka browser dan kunjungi:
```text
http://localhost:8000
```

---

## 🛠️ Fitur Utama

- **Playwright Async Verification**: Membuka URL video YouTube di background untuk verifikasi ketersediaan video, proteksi bot, atau status playability.
- **yt-dlp Extraction & Download**: Mendukung resolusi dari 360p, 480p, 720p hingga 1080p Full HD (MP4) serta ekstraksi MP3 Audio (192kbps).
- **Direct Browser Download**: File yang telah selesai diunduh dapat langsung disimpan ke laptop/komputer pengguna via tombol download `FileResponse`.
- **Manajemen Riwayat Unduhan**: Melihat daftar file di folder server dan opsi hapus langsung dari UI.
