# DOCUMENTATION GÉNÉRALE

Introduction
------------
"media_sociaux_downloader_final" est une collection d'applications locales (YouTube, TikTok, Instagram, Facebook) fournissant une interface web légère pour prévisualiser et télécharger des médias à l'aide d'une API Python (FastAPI) et yt-dlp. L'objectif est un outil personnel/éducatif pour récupérer des vidéos/images/audio localement.

Fonctionnalités communes
------------------------
- Prévisualisation : titre, auteur, miniature, durée.
- Téléchargement asynchrone via l'API.
- Choix de qualité et format (mp4, webm, mp3, jpg).
- Barre de progression et annulation.
- Endpoints REST pour l'info et le contrôle des jobs.
- Téléchargement stocké dans api/downloads/.

Organisation des sous-projets
-----------------------------
Les variantes sont organisées par dossier :
- yt_web/        → YouTube frontend + api/
- inst_web/      → Instagram frontend + api/
- tiktok_saver/  → TikTok (+ YouTube) frontend + api/
- fb_saver/      → Facebook frontend + api/

Chaque sous-projet expose habituellement :
- index.html, script.js, style.css (frontend)
- api/main.py (FastAPI) + requirements.txt + cookies.txt + downloads/

API — résumé rapide
-------------------
Base URL : http://localhost:8000 (par défaut dans chaque api/)
Principales routes (exemples communs) :
- GET /health → état du service
- POST /api/info → renvoie métadonnées (body: { "url": "..." })
- POST /api/download → démarre un téléchargement (body: { "url","quality","format" })
- GET /api/download/{task_id} → état & progression
- POST /api/download/{task_id}/pause|resume|cancel → contrôles
- GET /api/downloads → liste fichiers
- GET /api/downloads/{filename} → télécharger le fichier

Cookies
-------
- Certaines plateformes nécessitent des cookies (Netscape format) pour accéder à des contenus restreints.
- Placer le fichier dans api/cookies.txt.
- Ne PAS committer ce fichier. Traiter comme secret.

Journalisation & débogage
-------------------------
- Vu la nature I/O intensive (yt-dlp), conserver logs côté API et côté worker.
- Exemple basique : logging standard Python -> fichier rotating logs.
- En production, rediriger vers un système centralisé (ELK, Papertrail, Datadog).

Conformité légale et éthique
---------------------------
- Outil personnel : respectez les conditions d'utilisation des plateformes.
- Ne téléchargez que le contenu pour lequel vous avez le droit.
- Cookies contiennent des sessions — protéger la confidentialité.

Exemples d'utilisation (cURL)
------------------------------
1) Récupérer métadonnées :
curl -X POST http://localhost:8000/api/info -H "Content-Type: application/json" -d '{"url":"https://..."}'

2) Démarrer un téléchargement :
curl -X POST http://localhost:8000/api/download -H "Content-Type: application/json" -d '{"url":"https://...","quality":"720p","format":"mp4"}'

3) Vérifier progression :
curl http://localhost:8000/api/download/TASK_ID

Guide de contribution / bonnes pratiques
---------------------------------------
- Ne pas committer api/cookies.txt
- Tests unitaires pour la logique API et validation Pydantic
- Exiger variables d'environnement pour secrets (pas de valeurs codées en dur)
- Ajouter requirements.txt à jour dans chaque api/
- Documenter tout changement d'endpoint dans les README locaux
