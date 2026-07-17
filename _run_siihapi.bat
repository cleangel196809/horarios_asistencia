@echo off
chcp 65001 >nul 2>&1
title SIIHAPI - Django 8000
color 0E
cd /d "%~dp0SIIHAPI\backend"

echo.
echo  SIIHAPI - Politecnico Internacional
echo  http://localhost:8000
echo.

if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] No hay venv. Ejecuta iniciar_todo.bat primero.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
set DJANGO_SETTINGS_MODULE=siihapi.settings
echo [OK] venv activado
echo [OK] Aplicando migraciones...
python manage.py migrate --noinput 2>nul
echo [OK] Iniciando Django...
echo.

python manage.py runserver 0.0.0.0:8000

echo.
echo SIIHAPI detenido.
pause
