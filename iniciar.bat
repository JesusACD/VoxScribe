@echo off
chcp 65001 >nul
title VoxScribe - Transcriptor de YouTube y Audio
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [1/2] Creando entorno virtual de Python...
    python -m venv .venv
    echo [2/2] Instalando dependencias...
    .\.venv\Scripts\pip.exe install -r requirements.txt
)

echo.
echo =========================================================
echo   VoxScribe iniciando en http://localhost:8000
echo   Presiona Ctrl+C en esta ventana para detener el servidor
echo =========================================================
echo.

start "" http://localhost:8000
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
pause
