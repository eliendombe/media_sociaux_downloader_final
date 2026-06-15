"""
API FastAPI — backend Instagram Downloader (yt-dlp).
"""

from __future__ import annotations

import asyncio
import re
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yt_dlp
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

# ── Chemins ──────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR.parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
COOKIES_FILE = BASE_DIR / "cookies.txt"

DOWNLOADS_DIR.mkdir(exist_ok=True)

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Instagram Downloader API",
    description="Backend pour télécharger des médias Instagram (vidéos, reels, stories, images).",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Modèles ──────────────────────────────────────────────────────────────────


class Quality(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"
    audio = "audio"


class Format(str, Enum):
    mp4 = "mp4"
    jpg = "jpg"
    mp3 = "mp3"


class InfoRequest(BaseModel):
    url: HttpUrl


class DownloadRequest(BaseModel):
    url: HttpUrl
    quality: Quality = Quality.high
    format: Format = Format.mp4


class MediaInfo(BaseModel):
    id: str
    title: str
    uploader: str | None = None
    uploader_id: str | None = None
    thumbnail: str | None = None
    duration: int | None = None
    view_count: int | None = None
    like_count: int | None = None
    description: str | None = None
    is_video: bool = True
    webpage_url: str


class DownloadStatus(str, Enum):
    pending = "pending"
    downloading = "downloading"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"
    error = "error"


class DownloadTaskResponse(BaseModel):
    task_id: str
    status: DownloadStatus
    progress: float = Field(ge=0, le=100)
    filename: str | None = None
    error: str | None = None
    url: str


class DownloadedFile(BaseModel):
    name: str
    size: int
    created_at: str
    path: str


# ── Gestion des tâches ───────────────────────────────────────────────────────


class DownloadTask:
    def __init__(self, task_id: str, url: str) -> None:
        self.task_id = task_id
        self.url = url
        self.status = DownloadStatus.pending
        self.progress = 0.0
        self.filename: str | None = None
        self.error: str | None = None
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._cancelled = False
        self._lock = threading.Lock()

    def pause(self) -> None:
        with self._lock:
            if self.status == DownloadStatus.downloading:
                self.status = DownloadStatus.paused
                self._pause_event.clear()

    def resume(self) -> None:
        with self._lock:
            if self.status == DownloadStatus.paused:
                self.status = DownloadStatus.downloading
                self._pause_event.set()

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
            self.status = DownloadStatus.cancelled
            self._pause_event.set()

    def wait_if_paused(self) -> bool:
        """Retourne False si annulé."""
        while not self._pause_event.is_set():
            if self._cancelled:
                return False
            self._pause_event.wait(timeout=0.5)
        return not self._cancelled

    def to_response(self) -> DownloadTaskResponse:
        return DownloadTaskResponse(
            task_id=self.task_id,
            status=self.status,
            progress=round(self.progress, 1),
            filename=self.filename,
            error=self.error,
            url=self.url,
        )


_tasks: dict[str, DownloadTask] = {}


# ── Helpers yt-dlp ───────────────────────────────────────────────────────────


def _cookies_opts() -> dict[str, Any]:
    if COOKIES_FILE.is_file() and COOKIES_FILE.stat().st_size > 200:
        return {"cookiefile": str(COOKIES_FILE)}
    return {}


def _quality_format(quality: Quality, fmt: Format) -> str:
    if fmt == Format.mp3 or quality == Quality.audio:
        return "bestaudio/best"
    if fmt == Format.jpg:
        return "best"
    if quality == Quality.high:
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
    if quality == Quality.medium:
        return "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"
    return "worstvideo[ext=mp4]+worstaudio/worst"


def _base_ydl_opts(extract: bool = True) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        **_cookies_opts(),
    }
    if extract:
        opts["skip_download"] = True
    return opts


def _extract_info(url: str) -> dict[str, Any]:
    with yt_dlp.YoutubeDL(_base_ydl_opts(extract=True)) as ydl:
        return ydl.extract_info(url, download=False)


def _map_info(data: dict[str, Any]) -> MediaInfo:
    ext = data.get("ext", "mp4")
    return MediaInfo(
        id=data.get("id", ""),
        title=data.get("title") or data.get("description", "")[:120] or "Sans titre",
        uploader=data.get("uploader") or data.get("channel"),
        uploader_id=data.get("uploader_id") or data.get("channel_id"),
        thumbnail=data.get("thumbnail"),
        duration=data.get("duration"),
        view_count=data.get("view_count"),
        like_count=data.get("like_count"),
        description=(data.get("description") or "")[:500] or None,
        is_video=ext not in ("jpg", "jpeg", "png", "webp"),
        webpage_url=data.get("webpage_url") or data.get("original_url", ""),
    )


def _progress_hook(task: DownloadTask):
    def hook(d: dict[str, Any]) -> None:
        if not task.wait_if_paused():
            raise yt_dlp.utils.DownloadCancelled("Téléchargement annulé")

        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            if total:
                task.progress = min(99.0, (downloaded / total) * 100)
            task.status = DownloadStatus.downloading
        elif d["status"] == "finished":
            task.progress = 99.0

    return hook


def _run_download(task: DownloadTask, url: str, quality: Quality, fmt: Format) -> None:
    try:
        task.status = DownloadStatus.downloading

        out_template = str(DOWNLOADS_DIR / "%(title).80s [%(id)s].%(ext)s")
        ydl_opts: dict[str, Any] = {
            "outtmpl": out_template,
            "format": _quality_format(quality, fmt),
            "progress_hooks": [_progress_hook(task)],
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            **_cookies_opts(),
        }

        if fmt == Format.mp3 or quality == Quality.audio:
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ]

        if fmt == Format.jpg:
            ydl_opts["writethumbnail"] = True
            ydl_opts["skip_download"] = True
            ydl_opts["postprocessors"] = [
                {"key": "FFmpegThumbnailsConvertor", "format": "jpg"}
            ]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info:
                filepath = ydl.prepare_filename(info)
                path = Path(filepath)
                if fmt == Format.mp3 or quality == Quality.audio:
                    path = path.with_suffix(".mp3")
                elif fmt == Format.jpg:
                    path = path.with_suffix(".jpg")
                if path.exists():
                    task.filename = path.name

        if task._cancelled:
            task.status = DownloadStatus.cancelled
            if task.filename:
                (DOWNLOADS_DIR / task.filename).unlink(missing_ok=True)
            return

        task.progress = 100.0
        task.status = DownloadStatus.completed

    except yt_dlp.utils.DownloadCancelled:
        task.status = DownloadStatus.cancelled
        if task.filename:
            (DOWNLOADS_DIR / task.filename).unlink(missing_ok=True)
    except Exception as exc:
        task.status = DownloadStatus.error
        task.error = str(exc)


# ── Routes ───────────────────────────────────────────────────────────────────


@app.get("/")
async def serve_frontend() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "downloads_dir": str(DOWNLOADS_DIR),
        "cookies_configured": COOKIES_FILE.is_file() and COOKIES_FILE.stat().st_size > 200,
    }


@app.post("/api/info", response_model=MediaInfo)
async def get_media_info(body: InfoRequest) -> MediaInfo:
    """Récupère les métadonnées d'un post Instagram (aperçu)."""
    url = str(body.url)
    if not _is_supported_url(url):
        raise HTTPException(status_code=400, detail="URL Instagram non reconnue")

    try:
        data = await asyncio.to_thread(_extract_info, url)
        return _map_info(data)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Impossible d'analyser l'URL : {exc}") from exc


@app.post("/api/download", response_model=DownloadTaskResponse, status_code=202)
async def start_download(body: DownloadRequest, background_tasks: BackgroundTasks) -> DownloadTaskResponse:
    """Lance un téléchargement en arrière-plan."""
    url = str(body.url)
    if not _is_supported_url(url):
        raise HTTPException(status_code=400, detail="URL Instagram non reconnue")

    task_id = str(uuid.uuid4())
    task = DownloadTask(task_id, url)
    _tasks[task_id] = task

    background_tasks.add_task(_run_download, task, url, body.quality, body.format)
    return task.to_response()


@app.get("/api/download/{task_id}", response_model=DownloadTaskResponse)
async def get_download_status(task_id: str) -> DownloadTaskResponse:
    """Statut et progression d'une tâche."""
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return task.to_response()


@app.post("/api/download/{task_id}/pause", response_model=DownloadTaskResponse)
async def pause_download(task_id: str) -> DownloadTaskResponse:
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    task.pause()
    return task.to_response()


@app.post("/api/download/{task_id}/resume", response_model=DownloadTaskResponse)
async def resume_download(task_id: str) -> DownloadTaskResponse:
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    task.resume()
    return task.to_response()


@app.post("/api/download/{task_id}/cancel", response_model=DownloadTaskResponse)
async def cancel_download(task_id: str) -> DownloadTaskResponse:
    task = _tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    task.cancel()
    return task.to_response()


@app.get("/api/downloads", response_model=list[DownloadedFile])
async def list_downloads() -> list[DownloadedFile]:
    """Liste les fichiers déjà téléchargés."""
    files: list[DownloadedFile] = []
    for path in sorted(DOWNLOADS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_file() and path.name != ".gitkeep":
            stat = path.stat()
            files.append(
                DownloadedFile(
                    name=path.name,
                    size=stat.st_size,
                    created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                    path=f"/api/downloads/file/{path.name}",
                )
            )
    return files


@app.get("/api/downloads/folder")
async def downloads_folder() -> dict[str, str]:
    """Chemin absolu du dossier de téléchargements (pour le bouton 'Ouvrir le dossier')."""
    return {"path": str(DOWNLOADS_DIR.resolve())}


@app.get("/api/downloads/file/{filename}")
async def download_file(filename: str) -> FileResponse:
    """Télécharge / stream un fichier depuis le dossier downloads."""
    safe_name = Path(filename).name
    filepath = DOWNLOADS_DIR / safe_name
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(filepath, filename=safe_name)


# ── Validation URL ───────────────────────────────────────────────────────────

_INSTAGRAM_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:p|reel|reels|tv|stories)/[\w\-./]+",
    re.IGNORECASE,
)


def _is_supported_url(url: str) -> bool:
    return bool(_INSTAGRAM_RE.match(url))


app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
