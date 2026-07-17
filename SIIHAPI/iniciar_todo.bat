@echo off
title SIIHAPI - Lanzador SISCA + SIIHAPI
color 0E
cd /d "%~dp0"

echo.
echo ===============================================================
echo   LANZADOR INTEGRADO SISCA + SIIHAPI
echo ===============================================================
echo.
echo Este script arranca AMBAS aplicaciones en ventanas separadas:
echo.
echo   1. SISCA      en http://localhost:8080  (Flask, Control Asistencia)
echo   2. SIIHAPI    en http://localhost:8000  (Django, Horarios + IA)
echo.
pause

REM ── 1. Arrancar SISCA en una ventana nueva ──
echo.
echo --- Arrancando SISCA en puerto 8080 ---
set SISCA_DIR=%~dp0..\SISCA

if not exist "%SISCA_DIR%\venv\Scripts\activate.bat" (
    color 0C
    echo [ERROR] No hay venv de SISCA.
    echo Crea con: cd %SISCA_DIR% ^&^& python -m venv venv ^&^& venv\Scripts\activate ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

start "SISCA · Puerto 8080" cmd /k "cd /d %SISCA_DIR% && venv\Scripts\activate && python run.py"
echo [OK] SISCA arrancando en nueva ventana...

REM Esperar a que SISCA arranque
echo.
echo Esperando 10 segundos para que SISCA cargue...
timeout /t 10 /nobreak >nul

REM ── 2. Arrancar SIIHAPI ──
echo.
echo --- Arrancando SIIHAPI en puerto 8000 ---
cd backend
if not exist venv\Scripts\activate.bat (
    color 0C
    echo [ERROR] No hay venv en backend\venv. Ejecuta setup.bat primero.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat
set DJANGO_SETTINGS_MODULE=siihapi.settings

python manage.py migrate --noinput >nul 2>&1

echo.
echo ===============================================================
echo   SISTEMA INTEGRADO ARRANCANDO
echo ===============================================================
echo.
echo   SISCA      http://localhost:8080
echo   SIIHAPI    http://localhost:8000
echo.
echo   Login admin@pi.edu.co / Admin2026!
echo.
echo   Ctrl+C para detener SIIHAPI
echo ===============================================================
echo.

start /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000/login/"

python manage.py runserver 0.0.0.0:8000

echo.
echo Servidor SIIHAPI detenido.
echo Recuerda cerrar tambien la ventana de SISCA.
pause
