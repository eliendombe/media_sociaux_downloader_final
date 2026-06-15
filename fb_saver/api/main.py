"""
API FastAPI — backend téléchargeur vidéo (Facebook, YouTube, etc. via yt-dlp).
Lancer : uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import re
import threading
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

import yt_dlp
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
DOWNLOADS_DIR = BASE_DIR / "downloads"
COOKIES_FILE = BASE_DIR / "cookies.txt"

DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="FB Saver API",
    description="Backend de téléchargement vidéo (Facebook, YouTube, …)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- État des jobs en mémoire ---
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


class JobStatus(str, Enum):
    pending = "pending"
    downloading = "downloading"
    paused = "paused"
    completed = "completed"
    error = "error"
    cancelled = "cancelled"


class Quality(str, Enum):
    p720 = "720p"
    p480 = "480p"
    p360 = "360p"
    audio = "audio"


class MediaFormat(str, Enum):
    mp4 = "mp4"
    mp3 = "mp3"
    webm = "webm"


class AnalyzeRequest(BaseModel):
    url: HttpUrl


class DownloadRequest(BaseModel):
    url: HttpUrl
    quality: Quality = Quality.p720
    format: MediaFormat = MediaFormat.mp4


class VideoInfo(BaseModel):
    url: str
    title: str
    thumbnail: str | None = None
    duration: int | None = None
    uploader: str | None = None
    webpage_url: str | None = None
    extractor: str | None = None


class JobInfo(BaseModel):
    id: str
    status: JobStatus
    progress: float = Field(ge=0, le=100)
    message: str | None = None
    filename: str | None = None
    title: str | None = None
    error: str | None = None


class DownloadedFile(BaseModel):
    name: str
    size_bytes: int
    path: str


QUALITY_FORMAT: dict[Quality, str] = {
    Quality.p720: "bestvideo[height<=720]+bestaudio/best[height<=720]",
    Quality.p480: "bestvideo[height<=480]+bestaudio/best[height<=480]",
    Quality.p360: "bestvideo[height<=360]+bestaudio/best[height<=360]",
    Quality.audio: "bestaudio/best",
}

FORMAT_MERGE: dict[MediaFormat, str | None] = {
    MediaFormat.mp4: "mp4",
    MediaFormat.webm: "webm",
    MediaFormat.mp3: None,
}


def _cookies_usable() -> str | None:
    if not COOKIES_FILE.is_file():
        return None
    text = COOKIES_FILE.read_text(encoding="utf-8", errors="ignore")
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            return str(COOKIES_FILE)
    return None


def _base_ydl_opts() -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "restrictfilenames": True,
        "windowsfilenames": True,
    }
    cookiefile = _cookies_usable()
    if cookiefile:
        opts["cookiefile"] = cookiefile
    return opts


def _sanitize_filename(name: str, max_len: int = 80) -> str:
    """Nom sûr pour Windows (ASCII, sans emojis, longueur limitée)."""
    name = name.encode("ascii", "ignore").decode("ascii")
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name)
    name = re.sub(r"_+", "_", name)
    name = re.sub(r"\s+", " ", name).strip(" ._")
    if len(name) > max_len:
        name = name[:max_len].rstrip(" ._")
    return name or "video"


def _safe_download_path(stem: str, suffix: str) -> Path:
    """Évite les chemins trop longs (limite ~260 car. sous Windows)."""
    stem = _sanitize_filename(stem, max_len=80)
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    path = DOWNLOADS_DIR / f"{stem}{suffix}"
    max_path = 240
    if len(str(path)) > max_path:
        allowed = max(10, max_path - len(str(DOWNLOADS_DIR)) - len(suffix) - 1)
        stem = _sanitize_filename(stem, max_len=allowed)
        path = DOWNLOADS_DIR / f"{stem}{suffix}"
    return path


def _finalize_download_path(info: dict[str, Any], downloaded: Path, media_format: MediaFormat) -> Path:
    """Renomme le fichier %(id)s.ext en titre lisible mais sûr."""
    ext = ".mp3" if media_format == MediaFormat.mp3 else downloaded.suffix or ".mp4"
    video_id = str(info.get("id") or downloaded.stem)
    title = info.get("title") or "video"
    target = _safe_download_path(f"{title} [{video_id}]", ext)

    if not downloaded.is_file():
        return downloaded

    if target.exists() and target.resolve() != downloaded.resolve():
        target = _safe_download_path(f"{title} [{video_id}]_{uuid.uuid4().hex[:6]}", ext)

    if downloaded.resolve() != target.resolve():
        downloaded.rename(target)
    return target


def _progress_hook(job_id: str):
    def hook(d: dict[str, Any]) -> None:
        with _jobs_lock:
            job = _jobs.get(job_id)
            if not job:
                return
            if job.get("cancelled"):
                raise yt_dlp.utils.DownloadCancelled("Annulé par l'utilisateur")
            while job.get("paused") and not job.get("cancelled"):
                job["status"] = JobStatus.paused
                time.sleep(0.3)
                job = _jobs.get(job_id)
                if not job:
                    return
            if job.get("cancelled"):
                raise yt_dlp.utils.DownloadCancelled("Annulé par l'utilisateur")

            status = d.get("status")
            if status == "downloading":
                job["status"] = JobStatus.downloading
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                downloaded = d.get("downloaded_bytes") or 0
                if total and total > 0:
                    job["progress"] = min(99.0, round(100 * downloaded / total, 1))
                job["message"] = d.get("filename") or job.get("message")
            elif status == "finished":
                job["progress"] = 100.0
                job["message"] = "Post-traitement…"

    return hook


def _build_format_string(quality: Quality, media_format: MediaFormat) -> str:
    if media_format == MediaFormat.mp3 or quality == Quality.audio:
        return "bestaudio/best"
    fmt = QUALITY_FORMAT[quality]
    merge = FORMAT_MERGE[media_format]
    if merge:
        return f"{fmt}[ext={merge}]/best[ext={merge}]/{fmt}"
    return fmt


def _extract_info(url: str) -> dict[str, Any]:
    opts = {**_base_ydl_opts(), "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def _run_download(job_id: str, url: str, quality: Quality, media_format: MediaFormat) -> None:
    with _jobs_lock:
        job = _jobs[job_id]
        job["status"] = JobStatus.downloading

    # ID court pendant le téléchargement (évite titres Facebook énormes / emojis)
    outtmpl = str(DOWNLOADS_DIR / "%(id)s.%(ext)s")
    opts: dict[str, Any] = {
        **_base_ydl_opts(),
        "format": _build_format_string(quality, media_format),
        "outtmpl": outtmpl,
        "progress_hooks": [_progress_hook(job_id)],
    }

    if media_format == MediaFormat.mp3 or quality == Quality.audio:
        opts["format"] = "bestaudio/best"
        opts["postprocessors"] = [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }
        ]
        opts["keepvideo"] = False

    merge_ext = FORMAT_MERGE.get(media_format)
    if merge_ext and media_format != MediaFormat.mp3:
        opts.setdefault("postprocessors", []).append(
            {"key": "FFmpegVideoConvertor", "preferedformat": merge_ext}
        )

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filepath = Path(ydl.prepare_filename(info))
            if media_format == MediaFormat.mp3:
                filepath = filepath.with_suffix(".mp3")
            if not filepath.is_file():
                video_id = info.get("id")
                if video_id:
                    matches = sorted(
                        DOWNLOADS_DIR.glob(f"{video_id}.*"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    if matches:
                        filepath = matches[0]
                if not filepath.is_file():
                    candidates = [
                        p for p in DOWNLOADS_DIR.iterdir() if p.is_file() and p.name != ".gitkeep"
                    ]
                    if candidates:
                        filepath = max(candidates, key=lambda p: p.stat().st_mtime)

            if filepath.is_file():
                filepath = _finalize_download_path(info, filepath, media_format)

        with _jobs_lock:
            job = _jobs[job_id]
            if job.get("cancelled"):
                job["status"] = JobStatus.cancelled
                return
            job["status"] = JobStatus.completed
            job["progress"] = 100.0
            job["filename"] = filepath.name if filepath.is_file() else None
            job["title"] = info.get("title")
            job["message"] = "Téléchargement terminé"
    except yt_dlp.utils.DownloadCancelled:
        with _jobs_lock:
            job = _jobs[job_id]
            job["status"] = JobStatus.cancelled
            job["message"] = "Téléchargement annulé"
    except Exception as exc:
        with _jobs_lock:
            job = _jobs[job_id]
            job["status"] = JobStatus.error
            job["error"] = str(exc)
            job["message"] = "Erreur lors du téléchargement"


# --- Routes ---


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze", response_model=VideoInfo)
def analyze(body: AnalyzeRequest) -> VideoInfo:
    url = str(body.url)
    try:
        info = _extract_info(url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Impossible d'analyser l'URL : {exc}") from exc

    raw_duration = info.get("duration")
    duration = int(round(raw_duration)) if raw_duration is not None else None

    return VideoInfo(
        url=url,
        title=info.get("title") or "Sans titre",
        thumbnail=info.get("thumbnail"),
        duration=duration,
        uploader=info.get("uploader") or info.get("channel"),
        webpage_url=info.get("webpage_url") or url,
        extractor=info.get("extractor_key") or info.get("extractor"),
    )


@app.post("/api/download", response_model=JobInfo, status_code=202)
def start_download(body: DownloadRequest) -> JobInfo:
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {
            "id": job_id,
            "status": JobStatus.pending,
            "progress": 0.0,
            "message": "En file d'attente",
            "filename": None,
            "title": None,
            "error": None,
            "cancelled": False,
            "paused": False,
            "url": str(body.url),
        }

    thread = threading.Thread(
        target=_run_download,
        args=(job_id, str(body.url), body.quality, body.format),
        daemon=True,
    )
    thread.start()

    with _jobs_lock:
        return JobInfo(**{k: v for k, v in _jobs[job_id].items() if k in JobInfo.model_fields})


def _get_job_or_404(job_id: str) -> dict[str, Any]:
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return job


@app.get("/api/jobs/{job_id}", response_model=JobInfo)
def get_job(job_id: str) -> JobInfo:
    job = _get_job_or_404(job_id)
    return JobInfo(**{k: v for k, v in job.items() if k in JobInfo.model_fields})


@app.post("/api/jobs/{job_id}/pause", response_model=JobInfo)
def pause_job(job_id: str) -> JobInfo:
    job = _get_job_or_404(job_id)
    with _jobs_lock:
        job["paused"] = True
        if job["status"] == JobStatus.downloading:
            job["status"] = JobStatus.paused
    return JobInfo(**{k: v for k, v in job.items() if k in JobInfo.model_fields})


@app.post("/api/jobs/{job_id}/resume", response_model=JobInfo)
def resume_job(job_id: str) -> JobInfo:
    job = _get_job_or_404(job_id)
    with _jobs_lock:
        job["paused"] = False
        if job["status"] == JobStatus.paused:
            job["status"] = JobStatus.downloading
    return JobInfo(**{k: v for k, v in job.items() if k in JobInfo.model_fields})


@app.post("/api/jobs/{job_id}/cancel", response_model=JobInfo)
def cancel_job(job_id: str) -> JobInfo:
    job = _get_job_or_404(job_id)
    with _jobs_lock:
        job["cancelled"] = True
        job["paused"] = False
    return JobInfo(**{k: v for k, v in job.items() if k in JobInfo.model_fields})


@app.get("/api/downloads", response_model=list[DownloadedFile])
def list_downloads() -> list[DownloadedFile]:
    files: list[DownloadedFile] = []
    for path in sorted(DOWNLOADS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.is_file() and path.name != ".gitkeep":
            files.append(
                DownloadedFile(
                    name=path.name,
                    size_bytes=path.stat().st_size,
                    path=f"/api/downloads/{path.name}",
                )
            )
    return files


@app.get("/api/downloads/{filename}")
def download_file(filename: str) -> FileResponse:
    safe = Path(filename).name
    filepath = DOWNLOADS_DIR / safe
    if not filepath.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    return FileResponse(filepath, filename=safe)


@app.get("/api/open-downloads-folder")
def open_downloads_folder() -> dict[str, str]:
    """Retourne le chemin absolu du dossier (le client desktop peut l'ouvrir)."""
    return {"path": str(DOWNLOADS_DIR.resolve())}


app.mount(
    "/",
    StaticFiles(directory=str(PROJECT_ROOT), html=True),
    name="frontend",
)
