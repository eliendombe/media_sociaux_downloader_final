# media_sociaux_downloader_final

Une plateforme locale pour prévisualiser et télécharger des médias depuis les réseaux sociaux (YouTube, TikTok, Instagram, Facebook). Interfaces front-end légères (HTML/CSS/JS) couplées à une API Python (FastAPI) qui orchestre yt-dlp pour l'extraction et le téléchargement.

---

## Résumé
Ce guide explique comment cloner, préparer et exécuter les variantes (yt_web, inst_web, tiktok_saver, fb_saver). Le backend est en Python (FastAPI) et utilise yt-dlp pour l'extraction/téléchargement.

## Prérequis
- Python 3.10+ (recommandé)
- pip
- Git
- FFmpeg (recommandé pour conversion audio/vidéo)
- (Optionnel) Postgres/Redis si vous activez persistance/queue

Vérifier :
```
python --version
ffmpeg -version
```

## Cloner le dépôt
```
git clone https://github.com/eliendombe/media_sociaux_downloader_final.git
cd media_sociaux_downloader_final
```

## Installer et lancer une variante (ex : yt_web)
1) Aller dans le dossier api de la variante choisie :
```
cd yt_web/api
```

2) Créer un environnement virtuel et l'activer :
# Windows
```
python -m venv .venv
.\.venv\Scripts\activate
```
# macOS / Linux
```
python -m venv .venv
source .venv/bin/activate
```

3) Installer les dépendances :
```
pip install -r requirements.txt
```

(Optionnel) Ajouter dépendances de persistance si besoin :
```
pip install sqlmodel[asyncio] alembic  # ou sqlalchemy, databases, asyncpg selon la stack choisie
```

4) Configurer cookies (si nécessaire)
- Exporter cookies du navigateur au format Netscape et copier le contenu dans api/cookies.txt.
- Ne PAS committer ce fichier.

5) Lancer le serveur :
```
python main.py
# ou pour uvicorn explicitement :
# uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

6) Ouvrir l'UI :
- Si l'UI est servie par l'API (yt_web ou inst_web) : ouvrir http://localhost:8000
- Si l'UI est statique (tiktok_saver/frontends servis via http.server) : lancer `python -m http.server 5500` depuis le dossier racine de la variante et ouvrir http://127.0.0.1:5500

## Configuration d'environnement
Variables courantes (à exporter / .env)
- API_HOST=127.0.0.1
- API_PORT=8000
- DOWNLOADS_DIR=./api/downloads
- MAX_CONCURRENT_DOWNLOADS=3
- DATABASE_URL=sqlite:///./data.db  # ou postgresql://user:pw@host/db

## Exemples d'intégration backend / persistance
Voir ARCHITECTURE.md et DOCUMENTATION_GENERALE.md pour des exemples complets. Ci‑dessous un extrait minimal d'implémentation avec SQLModel (SQLite) pour persister les jobs.

### models.py (extrait)
```python
from datetime import datetime
from uuid import uuid4
from sqlmodel import SQLModel, Field
from typing import Optional

class DownloadJob(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    task_id: str = Field(index=True, default_factory=lambda: str(uuid4()))
    url: str
    platform: Optional[str] = None
    quality: Optional[str] = None
    format: Optional[str] = None
    status: str = "pending"  # pending, downloading, completed, failed, cancelled
    progress: float = 0.0
    filename: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
```

### db.py (extrait)
```python
from sqlmodel import create_engine, SQLModel, Session
from sqlalchemy.orm import sessionmaker
from typing import Generator
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data.db")
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})

def init_db():
    SQLModel.metadata.create_all(engine)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
```

### main.py (extrait pour créer un job)
```python
from fastapi import FastAPI, Depends, BackgroundTasks, HTTPException
from sqlmodel import Session, select
from models import DownloadJob
from db import init_db, get_session
import subprocess, os

app = FastAPI()

@app.on_event("startup")
def on_startup():
    init_db()

@app.post("/api/download", status_code=202)
def create_download(payload: dict, background_tasks: BackgroundTasks, session: Session = Depends(get_session)):
    url = payload.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    job = DownloadJob(url=url, quality=payload.get("quality"), format=payload.get("format"), status="pending")
    session.add(job)
    session.commit()
    session.refresh(job)
    # lancer tâche en background
    background_tasks.add_task(run_download_job, job.task_id)
    return {"task_id": job.task_id, "status": job.status}

def run_download_job(task_id: str):
    with SessionLocal() as session:
        job = session.exec(select(DownloadJob).where(DownloadJob.task_id==task_id)).one()
        try:
            job.status = "downloading"; job.progress = 0.0
            session.add(job); session.commit()
            # Exemple d'appel yt-dlp (simplifié)
            out_dir = os.getenv("DOWNLOADS_DIR", "./downloads")
            os.makedirs(out_dir, exist_ok=True)
            cmd = [
                "yt-dlp",
                "-o", os.path.join(out_dir, "%(title)s [%(id)s].%(ext)s"),
                job.url
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode == 0:
                job.status = "completed"
                job.progress = 100.0
                session.add(job); session.commit()
            else:
                job.status = "failed"
                session.add(job); session.commit()
        except Exception:
            job.status = "failed"
            session.add(job); session.commit()
```

## Checklist de mise en production
- [ ] Remplacer SQLite par Postgres (DATABASE_URL).
- [ ] Mettre en place migrations (Alembic).
- [ ] Externaliser la queue (Redis + RQ/Celery/Bull).
- [ ] Configurer un reverse-proxy (Nginx) et TLS.
- [ ] Limiter concurrence (throttle) et appliquer rate-limiting par IP/API key.
- [ ] Mettre en place authentification si service partagé (API keys / OAuth).
- [ ] Journaux centralisés (logs structurés JSON).
- [ ] Monitoring & alerting (healthchecks, Prometheus, Sentry).
- [ ] Backups réguliers des métadonnées & nettoyage automatique des fichiers anciens.
- [ ] Scanner et chiffrer les secrets (do not commit cookies.txt).
- [ ] Vérifier conformité légale et conditions d'utilisation des plateformes.

## Sécurité & exploitation
- Ne pas exposer l'API publiquement sans authentification.
- Limiter l'upload/URL length et valider les hôtes.
- Nettoyer les fichiers temporaires.
- Appliquer quotas et rejeter requêtes anormales.
- Surveiller l'utilisation de CPU/IO (yt-dlp et ffmpeg sont intensifs).

## Dépannage rapide
- yt-dlp obsolète → `pip install -U yt-dlp`
- Erreur FFmpeg → vérifier que ffmpeg est dans le PATH
- Frontend ne communique pas → servir via http.server ou s'assurer que l'API et la constante API_BASE pointent vers la bonne URL
- Ports occupés → modifier host/port ou fermer processus existant

## Support & contribution
- Ouvrez une issue pour signaler bugs ou proposer améliorations.
- Pour contributions majeures, proposez une PR avec tests et mise à jour de la documentation.
