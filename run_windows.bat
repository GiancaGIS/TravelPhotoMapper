@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    py -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install --upgrade pip
) else (
    call .venv\Scripts\activate.bat
)

python -m pip show travel-photo-mapper >nul 2>&1
if errorlevel 1 (
    python -m pip install -e .
    if errorlevel 1 exit /b 1
)

python -m travel_photo_mapper
if errorlevel 1 pause
