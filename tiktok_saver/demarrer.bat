@echo off
chcp 65001 >nul
title TikTok Saver — Demarrage
set "ROOT=%~dp0"
cd /d "%ROOT%"

echo ========================================
echo   TikTok Saver - Frontend + API
echo ========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python introuvable. Installez Python 3.10+ et ajoutez-le au PATH.
    pause
    exit /b 1
)

echo [1/3] Installation des dependances API...
cd /d "%ROOT%api"
python -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo [ERREUR] Echec pip install
    pause
    exit /b 1
)
cd /d "%ROOT%"

echo [2/3] Demarrage API FastAPI (port 8000)...
start "TikTok Saver - API" cmd /k cd /d "%ROOT%api" ^&^& python -m uvicorn main:app --host 127.0.0.1 --port 8000

echo Attente demarrage API...
timeout /t 3 /nobreak >nul

echo [3/3] Demarrage Frontend (port 5500)...
start "TikTok Saver - Frontend" cmd /k cd /d "%ROOT%" ^&^& python -m http.server 5500

timeout /t 2 /nobreak >nul

echo Ouverture du navigateur...
start "" "http://127.0.0.1:5500"

echo.
echo  Frontend : http://127.0.0.1:5500
echo  API      : http://127.0.0.1:8000
echo  Docs API : http://127.0.0.1:8000/docs
echo  Fichiers : %ROOT%api\downloads
echo.
echo  Fermez les fenetres "API" et "Frontend" pour arreter les serveurs.
echo.
pause
