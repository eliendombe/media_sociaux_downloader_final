# ARCHITECTURE — Résumé technique

But
----
Fournir une vue synthétique de l'architecture de la plateforme "media_sociaux_downloader_final" : interfaces web simples (HTML/CSS/JS) couplées à une API Python (FastAPI) qui orchestre yt-dlp pour l'extraction et le téléchargement, avec possibilité d'ajouter persistance et backend (jobs, métadonnées, fichiers).

Principaux composants
--------------------
- Frontend (statique) :
  - index.html, script.js, style.css (par variantes : yt_web, inst_web, tiktok_saver, fb_saver)
  - UI légère, appels REST vers l'API, prévisualisation et contrôle des téléchargements.
- Backend (API) :
  - FastAPI (api/main.py) : routes d'info, download, santé, fichiers, contrôle de tâches.
  - Uvicorn comme ASGI server.
  - yt-dlp en processus/environnement contrôlé pour extraction et téléchargement.
  - (Optionnel) FFmpeg pour post-traitement (MP3, mux/démux).
- Stockage local :
  - Dossier api/downloads/ pour fichiers finaux.
  - (Optionnel) Base de données relationnelle pour jobs & métadonnées (SQLite / Postgres).
- Lancement local :
  - Scripts Windows (demarrer.bat / start.bat) pour créer venv, installer dépendances et ouvrir UI.

Diagramme de flux (haut niveau)
-------------------------------
```mermaid
flowchart LR
    Browser[Client navigateur]
    UI[index.html + script.js]
    API["FastAPI (api/main.py)"]
    JobQueue[(Queue / Jobs)]
    Worker[Worker / Background Task]
    YTDLP[yt-dlp]
    FFmpeg[FFmpeg (optionnel)]
    Downloads[api/downloads/]
    DB[(Base de données: SQLite/Postgres)]
    Filesystem[(Fichiers + logs)]

    Browser --> UI
    UI -->|POST /api/info| API
    UI -->|POST /api/download| API
    API --> JobQueue
    JobQueue --> Worker
    Worker --> YTDLP
    YTDLP -->|raw files| Downloads
    Worker -->|post-process| FFmpeg
    Worker --> Downloads
    Worker --> DB
    API --> DB
    Downloads --> Filesystem
```

Flux de données et responsabilités
---------------------------------
- UI → API: demande d'info (métadonnées) et requête de téléchargement.
- API : valide la requête (Pydantic), crée un job, retourne un task_id (UUID).
- Worker/Background loop : exécute yt-dlp, enregistre progression (DB ou mémoire), effectue conversion (FFmpeg) si demandé, signale état final.
- Stockage : fichiers sur disque; métadonnées et état des jobs en base (recommandé pour production).
- Sécurité : cookies.txt (format Netscape) si nécessaire pour accéder à des contenus restreints (ne pas committer).

Options de persistance recommandées
-----------------------------------
- Développement local / prototype : SQLite via SQLModel (fichier local).
- Production simple : Postgres + SQLAlchemy / SQLModel + migrations Alembic.
- File/Queue pour scalabilité : Redis (pub/sub ou RQ/Celery) pour orchestration de jobs distribués.

Points d'attention (non exhaustif)
---------------------------------
- yt-dlp doit s'exécuter de façon isolée ; surveiller les temps d'exécution et la consommation disque.
- Cookies sensibles (api/cookies.txt) : ne pas versionner.
- Limiter le nombre de téléchargements concurrents (par défaut : 1–3) pour éviter IP-blocking.
- Prévoir nettoyage automatique des fichiers anciens ou mécanisme de quota.
