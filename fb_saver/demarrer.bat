@echo off
chcp 65001 >nul
title FB Saver — API + Frontend
cd /d "%~dp0api"

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Creation de l'environnement virtuel...
    python -m venv .venv
    if errorlevel 1 (
        echo ERREUR: Python introuvable. Installez Python 3.10+ et ajoutez-le au PATH.
        pause
        exit /b 1
    )
    echo [2/2] Installation des dependances...
    call .venv\Scripts\pip install -r requirements.txt
    if errorlevel 1 (
        echo ERREUR: echec pip install
        pause
        exit /b 1
    )
)

echo.
echo  API      : http://127.0.0.1:8000
echo  Frontend : http://127.0.0.1:8000
echo  Docs     : http://127.0.0.1:8000/docs
echo.
echo  Arret : Ctrl+C dans cette fenetre
echo.

start "" cmd /c "timeout /t 2 /nobreak >nul && start http://127.0.0.1:8000/"

call .venv\Scripts\uvicorn main:app --host 127.0.0.1 --port 8000 --reload

pause
