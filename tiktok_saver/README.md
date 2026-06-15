# TikTok Saver

Application web pour télécharger des vidéos **TikTok** et **YouTube** : interface dans le navigateur, traitement côté serveur via **FastAPI** et **yt-dlp**.

---

## Sommaire

1. [Vue d’ensemble](#vue-densemble)
2. [Architecture](#architecture)
3. [Prérequis](#prérequis)
4. [Démarrage rapide](#démarrage-rapide)
5. [Utilisation de l’interface](#utilisation-de-linterface)
6. [API REST](#api-rest)
7. [Cookies YouTube](#cookies-youtube)
8. [Démarrage manuel](#démarrage-manuel)
9. [Dépannage](#dépannage)
10. [Avertissement légal](#avertissement-légal)

---

## Vue d’ensemble

| Composant | Technologie | Port | Rôle |
|-----------|-------------|------|------|
| **Frontend** | HTML, CSS, JavaScript | `5500` | Saisie d’URL, aperçu, barre de progression |
| **Backend** | FastAPI + yt-dlp | `8000` | Analyse des liens, téléchargement, fichiers |
| **Lanceur** | `demarrer.bat` | — | Installe les deps, démarre les deux serveurs, ouvre le navigateur |

Les fichiers téléchargés sont enregistrés dans `api/downloads/`.

---

## Architecture

```
tiktok_saver/
├── demarrer.bat          # Lance frontend + API (Windows)
├── index.html            # Page principale
├── style.css             # Styles
├── script.js             # Logique UI + appels API
├── README.md             # Cette documentation
│
└── api/
    ├── main.py           # API FastAPI
    ├── requirements.txt  # Dépendances Python
    ├── cookies.txt       # Cookies YouTube (optionnel)
    └── downloads/        # Fichiers téléchargés
```

### Flux de données

```
Navigateur (5500)                    API (8000)
      │                                  │
      │  POST /info  ──────────────────► │  yt-dlp : métadonnées
      │  ◄────────────────────────────── │  (titre, auteur, miniature)
      │                                  │
      │  POST /download ───────────────► │  Téléchargement en arrière-plan
      │  GET /download/{id} (polling)  │  Progression 0–100 %
      │  DELETE /download/{id}           │  Annulation
      │                                  │
      │  GET /files/{name} ◄──────────── │  Récupération du fichier
      │  POST /open-folder ────────────► │  Ouvre api/downloads/ (Windows)
```

---

## Prérequis

| Outil | Version | Obligatoire | Usage |
|-------|---------|-------------|--------|
| **Python** | 3.10+ | Oui | API et serveur frontend |
| **FFmpeg** | récent | Oui* | Fusion vidéo/audio, MP3, MP4 |
| **pip** | — | Oui | Installation des paquets Python |

\* Sans FFmpeg, certains formats (MP3, MP4 fusionné) peuvent échouer.

### Installer FFmpeg (Windows)

1. Télécharger sur [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html) (build Windows).
2. Extraire et ajouter le dossier `bin` au **PATH** système.
3. Vérifier : `ffmpeg -version` dans un terminal.

### Installer les dépendances Python (manuel)

```powershell
cd api
python -m pip install -r requirements.txt
```

Contenu de `requirements.txt` : FastAPI, Uvicorn, yt-dlp, Pydantic.

---

## Démarrage rapide

1. Double-cliquer sur **`demarrer.bat`** à la racine du projet.
2. Le script :
   - installe les dépendances de l’API ;
   - ouvre une fenêtre **API** (port 8000) ;
   - ouvre une fenêtre **Frontend** (port 5500) ;
   - lance le navigateur sur [http://127.0.0.1:5500](http://127.0.0.1:5500).

3. Pour arrêter : fermer les fenêtres de terminal **TikTok Saver - API** et **TikTok Saver - Frontend**.

| URL | Description |
|-----|-------------|
| [http://127.0.0.1:5500](http://127.0.0.1:5500) | Interface utilisateur |
| [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) | Documentation interactive Swagger |
| [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc) | Documentation ReDoc |

---

## Utilisation de l’interface

1. **Coller une URL** TikTok ou YouTube dans le champ texte.
2. L’**aperçu** se charge automatiquement (titre, auteur, miniature) via l’API.
3. Choisir la **qualité** (`1080p`, `720p`, `480p`, `360p`, `Audio MP3`) et le **format** (`MP4`, `MP3`, `WebM`).
4. Cliquer sur le bouton **télécharger** (flèche vers le bas).
5. Suivre la **barre de progression** ; à la fin, un lien permet de récupérer le fichier.
6. **Annuler** : bouton croix (annule la tâche côté serveur).
7. **Dossier** : ouvre `api/downloads/` dans l’explorateur Windows.

> La pause n’est pas disponible : le téléchargement est géré par yt-dlp en une seule passe côté serveur.

### URLs supportées (exemples)

- TikTok : `https://www.tiktok.com/@user/video/1234567890`
- TikTok court : `https://vm.tiktok.com/...`
- YouTube : `https://www.youtube.com/watch?v=...`
- YouTube court : `https://youtu.be/...`

---

## API REST

Base URL : `http://127.0.0.1:8000`

Le frontend utilise cette adresse (définie dans `script.js` : `API_BASE`).

### Santé

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/health` | Vérifie que l’API répond |

**Réponse exemple :**
```json
{
  "status": "ok",
  "downloads_dir": "E:\\...\\api\\downloads"
}
```

---

### Métadonnées vidéo

| Méthode | Route | Description |
|---------|-------|-------------|
| `POST` | `/info` | Titre, auteur, miniature, plateforme |

**Corps :**
```json
{
  "url": "https://www.tiktok.com/@user/video/123"
}
```

**Réponse exemple :**
```json
{
  "url": "https://www.tiktok.com/...",
  "title": "Titre de la vidéo",
  "author": "@username",
  "thumbnail": "https://...",
  "duration": 42,
  "platform": "tiktok"
}
```

---

### Téléchargement

| Méthode | Route | Description |
|---------|-------|-------------|
| `POST` | `/download` | Démarre un téléchargement (réponse `202`) |
| `GET` | `/download/{task_id}` | État et progression de la tâche |
| `DELETE` | `/download/{task_id}` | Annule une tâche en cours |

**Corps `POST /download` :**
```json
{
  "url": "https://www.tiktok.com/@user/video/123",
  "quality": "720p",
  "format": "mp4"
}
```

| Champ `quality` | Valeurs |
|-----------------|---------|
| Qualité vidéo | `1080p`, `720p`, `480p`, `360p` |
| Audio seul | `audio` |

| Champ `format` | Valeurs |
|----------------|---------|
| Formats | `mp4`, `mp3`, `webm` |

**Statuts de tâche (`status`) :**

| Valeur | Signification |
|--------|---------------|
| `pending` | En file d’attente |
| `downloading` | Téléchargement en cours |
| `completed` | Terminé (`filename` renseigné) |
| `failed` | Erreur (`message` détaille la cause) |
| `cancelled` | Annulé par l’utilisateur |

**Exemple de suivi :**
```http
GET /download/a1b2c3d4-...
```
```json
{
  "task_id": "a1b2c3d4-...",
  "status": "downloading",
  "progress": 67.5,
  "message": " 67.5%",
  "filename": null,
  "file_path": null
}
```

---

### Fichiers

| Méthode | Route | Description |
|---------|-------|-------------|
| `GET` | `/files` | Liste des fichiers dans `downloads/` |
| `GET` | `/files/{filename}` | Télécharge ou lit un fichier |
| `DELETE` | `/files/{filename}` | Supprime un fichier |
| `POST` | `/open-folder` | Ouvre le dossier `downloads/` (OS local) |

**Paramètre query pour forcer le téléchargement :**
```
GET /files/mon_fichier.mp4?download=true
```

---

### Exemple cURL

```bash
# Infos vidéo
curl -X POST http://127.0.0.1:8000/info \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"https://www.tiktok.com/@user/video/123\"}"

# Lancer un téléchargement
curl -X POST http://127.0.0.1:8000/download \
  -H "Content-Type: application/json" \
  -d "{\"url\": \"https://www.tiktok.com/@user/video/123\", \"quality\": \"720p\", \"format\": \"mp4\"}"

# Progression (remplacer TASK_ID)
curl http://127.0.0.1:8000/download/TASK_ID
```

---

## Cookies YouTube

Certaines vidéos YouTube nécessitent une session connectée.

1. Se connecter à [https://www.youtube.com](https://www.youtube.com) dans le navigateur.
2. Exporter les cookies au format **Netscape** (extension du type *Get cookies.txt LOCALLY*).
3. Coller le contenu dans **`api/cookies.txt`** (remplacer les commentaires d’exemple).
4. Redémarrer l’API.

Pour TikTok uniquement, `cookies.txt` peut rester vide ou commenté.

> Ne partagez jamais `cookies.txt` : il contient des identifiants de session.

---

## Démarrage manuel

Sans `demarrer.bat`, dans deux terminaux :

**Terminal 1 — API :**
```powershell
cd api
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload
```

**Terminal 2 — Frontend :**
```powershell
cd ..   # racine tiktok_saver
python -m http.server 5500
```

Puis ouvrir [http://127.0.0.1:5500](http://127.0.0.1:5500).

> Ouvrir `index.html` directement (`file://`) ne fonctionne pas correctement avec l’API : utiliser le serveur HTTP sur le port 5500.

---

## Dépannage

| Problème | Cause probable | Solution |
|----------|----------------|----------|
| « API hors ligne » dans l’UI | API non démarrée | Lancer `demarrer.bat` ou uvicorn manuellement |
| Erreur FFmpeg | FFmpeg absent du PATH | Installer FFmpeg et redémarrer le terminal |
| YouTube « Sign in » / 403 | Cookies manquants | Remplir `api/cookies.txt` |
| TikTok échoue | Lien expiré ou yt-dlp obsolète | `pip install -U yt-dlp` dans `api/` |
| Port déjà utilisé | Autre processus sur 8000/5500 | Fermer l’ancien serveur ou changer le port dans `demarrer.bat` / `script.js` |
| CORS / fetch bloqué | Frontend ouvert en `file://` | Servir le frontend via `python -m http.server 5500` |

### Mettre à jour yt-dlp

```powershell
cd api
python -m pip install -U yt-dlp
```

### Changer l’URL de l’API (frontend)

Dans `script.js`, modifier la constante :

```javascript
const API_BASE = "http://127.0.0.1:8000";
```

---

## Avertissement légal

Ce projet est un outil technique à usage personnel ou éducatif. Le téléchargement de contenus peut être soumis aux **conditions d’utilisation** de TikTok, YouTube et aux **droits d’auteur** des créateurs. Utilisez-le uniquement pour du contenu dont vous avez le droit de télécharger ou archiver.

---

## Licence

Projet personnel — précisez une licence si vous publiez le dépôt (MIT, etc.).
