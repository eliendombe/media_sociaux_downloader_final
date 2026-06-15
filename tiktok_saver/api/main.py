"""
API FastAPI — backend TikTok / YouTube saver (yt-dlp).
"""

from __future__ import annotations

import os
import platform
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yt_dlp
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl

API_DIR = Path(__file__).resolve().parent
DOWNLOADS_DIR = API_DIR / "downloads"
COOKIES_FILE = API_DIR / "cookies.txt"

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="TikTok Saver API",
    description="Téléchargement TikTok / YouTube via yt-dlp",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TaskStatus(str, Enum):
    PENDING = "pending"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Quality(str, Enum):
    P1080 = "1080p"
    P720 = "720p"
    P480 = "480p"
    P360 = "360p"
    AUDIO = "audio"


class Format(str, Enum):
    MP4 = "mp4"
    MP3 = "mp3"
    WEBM = "webm"


class VideoInfoRequest(BaseModel):
    url: HttpUrl


class VideoInfoResponse(BaseModel):
    url: str
    title: str
    author: str
    thumbnail: str | None = None
    duration: int | None = None
    platform: str


class DownloadRequest(BaseModel):
    url: HttpUrl
    quality: Quality = Quality.P720
    format: Format = Format.MP4


class DownloadTaskResponse(BaseModel):
    task_id: str
    status: TaskStatus
    progress: float = Field(ge=0, le=100)
    message: str | None = None
    filename: str | None = None
    file_path: str | None = None


class FileItem(BaseModel):
    name: str
    size_bytes: int
    created_at: str


_tasks: dict[str, dict[str, Any]] = {}
_tasks_lock = threading.Lock()
_cancel_flags: dict[str, threading.Event] = {}


def _cookies_usable() -> bool:
    if not COOKIES_FILE.is_file():
        return False
    text = COOKIES_FILE.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return True
    return False


def _base_ydl_opts() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if _cookies_usable():
        opts["cookiefile"] = str(COOKIES_FILE)
    return opts


def _detect_platform(url: str) -> str:
    u = url.lower()
    if "tiktok.com" in u or "vm.tiktok.com" in u:
        return "tiktok"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    return "unknown"


def _quality_format_selector(quality: Quality, fmt: Format) -> str | None:
    if fmt == Format.MP3 or quality == Quality.AUDIO:
        return "bestaudio/best"
    height_map = {
        Quality.P1080: 1080,
        Quality.P720: 720,
        Quality.P480: 480,
        Quality.P360: 360,
    }
    h = height_map.get(quality, 720)
    if fmt == Format.WEBM:
        return f"bestvideo[height<={h}][ext=webm]+bestaudio[ext=webm]/best[height<={h}][ext=webm]/best"
    return f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]/best[height<={h}][ext=mp4]/best"


def _postprocessors(fmt: Format) -> list[dict[str, Any]]:
    if fmt == Format.MP3:
        return [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
    if fmt == Format.MP4:
        return [{"key": "FFmpegVideoConvertor", "preferedformat": "mp4"}]
    return []


def _output_template(task_id: str) -> str:
    return str(DOWNLOADS_DIR / f"{task_id}_%(title).80B.%(ext)s")


def _extract_info(url: str, download: bool = False, ydl_opts: dict | None = None) -> dict:
    opts = {**_base_ydl_opts(), **(ydl_opts or {})}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=download)


def _update_task(task_id: str, **kwargs: Any) -> None:
    with _tasks_lock:
        if task_id in _tasks:
            _tasks[task_id].update(kwargs)


def _run_download(task_id: str, url: str, quality: Quality, fmt: Format) -> None:
    cancel = _cancel_flags[task_id]
    downloaded_file: list[str | None] = [None]

    def progress_hook(d: dict) -> None:
        if cancel.is_set():
            raise yt_dlp.utils.DownloadError("Téléchargement annulé")

        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes") or 0
            pct = (downloaded / total * 100) if total else 0
            _update_task(
                task_id,
                status=TaskStatus.DOWNLOADING,
                progress=round(min(pct, 99), 1),
                message=d.get("_percent_str", "").strip() or None,
            )
        elif status == "finished":
            downloaded_file[0] = d.get("filename")
            _update_task(task_id, progress=99, message="Finalisation…")

    try:
        _update_task(task_id, status=TaskStatus.DOWNLOADING, progress=0, message="Démarrage…")

        ydl_opts: dict[str, Any] = {
            **_base_ydl_opts(),
            "format": _quality_format_selector(quality, fmt),
            "outtmpl": _output_template(task_id),
            "progress_hooks": [progress_hook],
            "postprocessors": _postprocessors(fmt),
            "merge_output_format": "mp4" if fmt == Format.MP4 else None,
        }
        if fmt == Format.MP3 or quality == Quality.AUDIO:
            ydl_opts["format"] = "bestaudio/best"

        info = _extract_info(str(url), download=True, ydl_opts=ydl_opts)

        if cancel.is_set():
            _update_task(task_id, status=TaskStatus.CANCELLED, message="Annulé")
            return

        # Fichier final sur disque
        final_path = downloaded_file[0]
        if not final_path and info:
            requested = info.get("requested_downloads") or []
            if requested:
                final_path = requested[0].get("filepath")
            if not final_path:
                final_path = info.get("_filename")

        filename = Path(final_path).name if final_path else None

        _update_task(
            task_id,
            status=TaskStatus.COMPLETED,
            progress=100,
            message="Terminé",
            filename=filename,
            file_path=str(final_path) if final_path else None,
        )
    except yt_dlp.utils.DownloadError as e:
        if cancel.is_set() or "annulé" in str(e).lower():
            _update_task(task_id, status=TaskStatus.CANCELLED, message="Annulé")
        else:
            _update_task(
                task_id,
                status=TaskStatus.FAILED,
                progress=0,
                message=str(e),
            )
    except Exception as e:
        _update_task(
            task_id,
            status=TaskStatus.FAILED,
            progress=0,
            message=str(e),
        )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "downloads_dir": str(DOWNLOADS_DIR)}


@app.post("/info", response_model=VideoInfoResponse)
def video_info(body: VideoInfoRequest) -> VideoInfoResponse:
    url = str(body.url)
    try:
        info = _extract_info(url, download=False)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Impossible d'analyser l'URL : {e}") from e

    author = (
        info.get("uploader")
        or info.get("channel")
        or info.get("creator")
        or "unknown"
    )
    if info.get("uploader_id"):
        author = f"@{info['uploader_id']}" if not author.startswith("@") else author

    return VideoInfoResponse(
        url=url,
        title=info.get("title") or "Sans titre",
        author=author,
        thumbnail=info.get("thumbnail"),
        duration=info.get("duration"),
        platform=_detect_platform(url),
    )


@app.post("/download", response_model=DownloadTaskResponse, status_code=202)
def start_download(body: DownloadRequest) -> DownloadTaskResponse:
    url = str(body.url)
    platform = _detect_platform(url)
    if platform == "unknown":
        raise HTTPException(
            status_code=400,
            detail="URL non supportée. Utilisez un lien TikTok ou YouTube.",
        )

    task_id = str(uuid.uuid4())
    cancel = threading.Event()
    _cancel_flags[task_id] = cancel

    with _tasks_lock:
        _tasks[task_id] = {
            "task_id": task_id,
            "url": url,
            "status": TaskStatus.PENDING,
            "progress": 0,
            "message": "En file d'attente",
            "filename": None,
            "file_path": None,
            "quality": body.quality.value,
            "format": body.format.value,
        }

    thread = threading.Thread(
        target=_run_download,
        args=(task_id, url, body.quality, body.format),
        daemon=True,
    )
    thread.start()

    return DownloadTaskResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        progress=0,
        message="En file d'attente",
    )


@app.get("/download/{task_id}", response_model=DownloadTaskResponse)
def get_download_status(task_id: str) -> DownloadTaskResponse:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")

    return DownloadTaskResponse(
        task_id=task_id,
        status=task["status"],
        progress=task.get("progress", 0),
        message=task.get("message"),
        filename=task.get("filename"),
        file_path=task.get("file_path"),
    )


@app.delete("/download/{task_id}", response_model=DownloadTaskResponse)
def cancel_download(task_id: str) -> DownloadTaskResponse:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")

    if task["status"] in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        return DownloadTaskResponse(
            task_id=task_id,
            status=task["status"],
            progress=task.get("progress", 0),
            message=task.get("message"),
            filename=task.get("filename"),
        )

    cancel = _cancel_flags.get(task_id)
    if cancel:
        cancel.set()
    _update_task(task_id, status=TaskStatus.CANCELLED, message="Annulation demandée")

    return DownloadTaskResponse(
        task_id=task_id,
        status=TaskStatus.CANCELLED,
        progress=task.get("progress", 0),
        message="Annulation demandée",
    )


@app.get("/files", response_model=list[FileItem])
def list_files() -> list[FileItem]:
    items: list[FileItem] = []
    for path in sorted(DOWNLOADS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        stat = path.stat()
        items.append(
            FileItem(
                name=path.name,
                size_bytes=stat.st_size,
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            )
        )
    return items


@app.get("/files/{filename}")
def get_file(filename: str, download: bool = Query(False, description="Forcer le téléchargement")):
    safe_name = Path(filename).name
    path = DOWNLOADS_DIR / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")

    return FileResponse(
        path,
        filename=safe_name if download else None,
        media_type="application/octet-stream",
    )


@app.delete("/files/{filename}")
def delete_file(filename: str) -> dict[str, str]:
    safe_name = Path(filename).name
    path = DOWNLOADS_DIR / safe_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    path.unlink()
    return {"deleted": safe_name}


@app.post("/open-folder")
def open_downloads_folder() -> dict[str, str]:
    path = str(DOWNLOADS_DIR.resolve())
    try:
        if platform.system() == "Windows":
            os.startfile(path)
        elif platform.system() == "Darwin":
            subprocess.run(["open", path], check=True)
        else:
            subprocess.run(["xdg-open", path], check=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    return {"path": path}
