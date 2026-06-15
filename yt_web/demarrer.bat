@echo off
chcp 65001 >nul
title YouTube Downloader - Lanceur
cd /d "%~dp0"

echo ========================================
echo   YouTube Downloader - Demarrage
echo ========================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou pas dans le PATH.
    pause
    exit /b 1
)

if not exist "api\.venv\Scripts\python.exe" (
    echo Creation de l'environnement virtuel...
    cd api
    python -m venv .venv
    if errorlevel 1 (
        echo [ERREUR] Impossible de creer le venv.
        pause
        exit /b 1
    )
    call .venv\Scripts\activate.bat
    echo Installation des dependances API...
    pip install -r requirements.txt
    cd ..
) else (
    echo Environnement virtuel API : OK
)

echo.
echo Application : http://localhost:8008
echo Docs API      : http://localhost:8008/docs
echo.
echo Une fenetre API va s'ouvrir. Fermez-la pour arreter.
echo.

start "YT API :8000" cmd /k "cd /d %~dp0api && call .venv\Scripts\activate.bat && python main.py"

timeout /t 2 /nobreak >nul
start http://localhost:8008 

echo Navigateur ouvert sur l'application.
pause
