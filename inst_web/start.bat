@echo off
chcp 65001 >nul
title Instagram Downloader - Demarrage

cd /d "%~dp0api"

REM Environnement virtuel optionnel (api\.venv)
if exist "%~dp0api\.venv\Scripts\activate.bat" (
    call "%~dp0api\.venv\Scripts\activate.bat"
)

echo ========================================
echo   Instagram Downloader
echo ========================================
echo.
echo   API    : http://localhost:8000
echo   Front  : http://localhost:8000
echo   Docs   : http://localhost:8000/docs
echo.
echo   Fermez la fenetre "API" pour arreter le serveur.
echo.

REM Verifier Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python introuvable. Installez Python et ajoutez-le au PATH.
    pause
    exit /b 1
)

REM Installer les dependances si besoin
pip show fastapi >nul 2>&1
if errorlevel 1 (
    echo Installation des dependances...
    pip install -r requirements.txt
    echo.
)

REM Lancer l'API (sert aussi le frontend) dans une nouvelle fenetre
start "Instagram Downloader - API" cmd /k ""%~dp0api\run_server.bat""

REM Attendre que le serveur demarre puis ouvrir le navigateur
timeout /t 3 /nobreak >nul
start "" http://localhost:8000

echo Navigateur ouvert. Le serveur tourne dans l'autre fenetre.
echo.
pause
