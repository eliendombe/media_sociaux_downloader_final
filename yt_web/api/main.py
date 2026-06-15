"""
API FastAPI — backend YouTube Downloader (yt-dlp).
"""

from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

# --- Chemins -----------------------------------------------------------------

API_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = API_DIR.parent
DOWNLOADS_DIR = API_DIR / "downloads"
COOKIES_FILE = API_DIR / "cookies.txt"

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

# --- Modèles -----------------------------------------------------------------


class VideoQuality(str, Enum):
    p1080 = "1080p"
    p720 = "720p"
    p480 = "480p"
    p360 = "360p"
    audio = "audio"


class VideoFormat(str, Enum):
    mp4 = "mp4"
    mp3 = "mp3"
    webm = "webm"


class JobStatus(str, Enum):
    pending = "pending"
    downloading = "downloading"
    completed = "completed"
    error = "error"
    cancelled = "cancelled"


class VideoInfoRequest(BaseModel):
    url: HttpUrl


class VideoInfoResponse(BaseModel):
    id: str
    title: str
    channel: str
    duration: int | None
    thumbnail: str | None
    webpage_url: str


class DownloadRequest(BaseModel):
    url: HttpUrl
    quality: VideoQuality = VideoQuality.p1080
    format: VideoFormat = VideoFormat.mp4


class DownloadJobResponse(BaseModel):
    job_id: str
    status: JobStatus
    progress: float = Field(ge=0, le=100)
    message: str | None = None
    filename: str | None = None
    created_at: str
    updated_at: str


class DownloadedFile(BaseModel):
    name: str
    size: int
    modified_at: str


# --- Gestion des jobs --------------------------------------------------------


class _JobState:
    __slots__ = (
        "job_id",
        "status",
        "progress",
        "message",
        "filename",
        "cancel_event",
        "thread",
        "created_at",
        "updated_at",
    )

    def __init__(self, job_id: str) -> None:
        now = _utc_now()
        self.job_id = job_id
        self.status = JobStatus.pending
        self.progress = 0.0
        self.message: str | None = None
        self.filename: str | None = None
        self.cancel_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.created_at = now
        self.updated_at = now

    def touch(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(self, key, value)
        self.updated_at = _utc_now()

    def to_response(self) -> DownloadJobResponse:
        return DownloadJobResponse(
            job_id=self.job_id,
            status=self.status,
            progress=round(self.progress, 1),
            message=self.message,
            filename=self.filename,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


_jobs: dict[str, _JobState] = {}
_jobs_lock = threading.Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _cookies_path() -> str | None:
    if not COOKIES_FILE.is_file():
        return None
    text = COOKIES_FILE.read_text(encoding="utf-8", errors="ignore")
    lines = [
        ln
        for ln in text.splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]
    if not lines:
        return None
    return str(COOKIES_FILE)


def _quality_format_opts(quality: VideoQuality, fmt: VideoFormat) -> dict[str, Any]:
    if fmt == VideoFormat.mp3 or quality == VideoQuality.audio:
        return {
            "format": "bestaudio/best",
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }
            ],
            "merge_output_format": None,
        }

    height_map = {
        VideoQuality.p1080: 1080,
        VideoQuality.p720: 720,
        VideoQuality.p480: 480,
        VideoQuality.p360: 360,
    }
    h = height_map.get(quality, 1080)
    video_fmt = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]/best"

    opts: dict[str, Any] = {"format": video_fmt}
    if fmt == VideoFormat.webm:
        opts["merge_output_format"] = "webm"
    else:
        opts["merge_output_format"] = "mp4"
    return opts


def _base_ydl_opts() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "outtmpl": str(DOWNLOADS_DIR / "%(title).200B [%(id)s].%(ext)s"),
        "restrictfilenames": False,
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "socket_timeout": 30,
    }
    cookies = _cookies_path()
    if cookies:
        opts["cookiefile"] = cookies
    return opts


def _extract_info(url: str) -> dict[str, Any]:
    opts = {**_base_ydl_opts(), "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _run_download(job: _JobState, url: str, quality: VideoQuality, fmt: VideoFormat) -> None:
    def progress_hook(data: dict[str, Any]) -> None:
        if job.cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Téléchargement annulé")
        if data.get("status") == "downloading":
            total = data.get("total_bytes") or data.get("total_bytes_estimate")
            downloaded = data.get("downloaded_bytes", 0)
            if total and total > 0:
                pct = min(99.0, downloaded / total * 100)
                job.touch(status=JobStatus.downloading, progress=pct)
        elif data.get("status") == "finished":
            job.touch(progress=99.0)

    qf = _quality_format_opts(quality, fmt)
    opts = {
        **_base_ydl_opts(),
        **qf,
        "progress_hooks": [progress_hook],
    }

    try:
        job.touch(status=JobStatus.downloading, progress=0.0, message="Démarrage…")
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise ValueError("Impossible d'extraire les métadonnées")

            filepath = Path(ydl.prepare_filename(info))
            if not filepath.exists():
                candidates = list(DOWNLOADS_DIR.glob(f"*{info.get('id', '')}*"))
                filepath = candidates[0] if candidates else filepath

            job.touch(
                status=JobStatus.completed,
                progress=100.0,
                filename=filepath.name if filepath.exists() else None,
                message="Téléchargement terminé",
            )
    except yt_dlp.utils.DownloadCancelled:
        job.touch(
            status=JobStatus.cancelled,
            message="Téléchargement annulé",
        )
    except Exception as exc:
        job.touch(
            status=JobStatus.error,
            message=str(exc) or "Erreur inconnue",
        )


def _start_job(url: str, quality: VideoQuality, fmt: VideoFormat) -> _JobState:
    job_id = str(uuid.uuid4())
    job = _JobState(job_id)
    thread = threading.Thread(
        target=_run_download,
        args=(job, str(url), quality, fmt),
        daemon=True,
        name=f"download-{job_id[:8]}",
    )
    job.thread = thread
    with _jobs_lock:
        _jobs[job_id] = job
    thread.start()
    return job


# --- Application -------------------------------------------------------------

app = FastAPI(
    title="YouTube Downloader API",
    description="Backend FastAPI pour télécharger des vidéos YouTube via yt-dlp.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/info", response_model=VideoInfoResponse)
def video_info(body: VideoInfoRequest) -> VideoInfoResponse:
    try:
        info = _extract_info(str(body.url))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"URL invalide ou inaccessible : {exc}") from exc

    return VideoInfoResponse(
        id=info.get("id", ""),
        title=info.get("title", "Sans titre"),
        channel=info.get("uploader") or info.get("channel", "Inconnu"),
        duration=info.get("duration"),
        thumbnail=info.get("thumbnail"),
        webpage_url=info.get("webpage_url", str(body.url)),
    )


@app.post("/api/download", response_model=DownloadJobResponse, status_code=202)
def start_download(body: DownloadRequest) -> DownloadJobResponse:
    url = str(body.url)
    if not _is_youtube_url(url):
        raise HTTPException(status_code=400, detail="Seuls les liens YouTube sont acceptés")

    active = _count_active_jobs()
    if active >= 3:
        raise HTTPException(
            status_code=429,
            detail="Trop de téléchargements simultanés (max 3). Réessayez plus tard.",
        )

    job = _start_job(url, body.quality, body.format)
    return job.to_response()


@app.get("/api/download/{job_id}", response_model=DownloadJobResponse)
def get_download_status(job_id: str) -> DownloadJobResponse:
    job = _get_job(job_id)
    return job.to_response()


@app.post("/api/download/{job_id}/cancel", response_model=DownloadJobResponse)
def cancel_download(job_id: str) -> DownloadJobResponse:
    job = _get_job(job_id)
    if job.status in (JobStatus.completed, JobStatus.error, JobStatus.cancelled):
        return job.to_response()
    job.cancel_event.set()
    job.touch(status=JobStatus.cancelled, message="Annulation en cours…")
    return job.to_response()


@app.get("/api/downloads", response_model=list[DownloadedFile])
def list_downloads() -> list[DownloadedFile]:
    files: list[DownloadedFile] = []
    for path in sorted(DOWNLOADS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file() or path.name.startswith("."):
            continue
        stat = path.stat()
        files.append(
            DownloadedFile(
                name=path.name,
                size=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            )
        )
    return files


@app.get("/api/downloads/{filename}")
def download_file(filename: str) -> FileResponse:
    safe = _safe_filename(filename)
    path = DOWNLOADS_DIR / safe
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(path, filename=safe, media_type="application/octet-stream")


# --- Utilitaires -------------------------------------------------------------


_YT_RE = re.compile(
    r"^(https?://)?(www\.)?(youtube\.com|youtu\.be)/",
    re.IGNORECASE,
)


def _is_youtube_url(url: str) -> bool:
    return bool(_YT_RE.search(url))


def _safe_filename(name: str) -> str:
    if ".." in name or "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide")
    return name


def _get_job(job_id: str) -> _JobState:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return job


def _count_active_jobs() -> int:
    with _jobs_lock:
        return sum(
            1
            for j in _jobs.values()
            if j.status in (JobStatus.pending, JobStatus.downloading)
        )


# Interface web (index.html à la racine du projet) — monté en dernier
if (PROJECT_ROOT / "index.html").is_file():
    app.mount(
        "/",
        StaticFiles(directory=str(PROJECT_ROOT), html=True),
        name="frontend",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8008, reload=True)
