@echo off
chcp 65001 >nul
title SISCA · Flask 8080

cd /d "%~dp0"

echo.
echo ═══════════════════════════════════════════════════════════
echo   SISCA v1.0 · Politecnico Internacional
echo   Sistema Institucional de Control de Asistencia
echo ═══════════════════════════════════════════════════════════
echo.

if not exist "venv\Scripts\activate.bat" (
    color 0C
    echo [ERROR] No hay entorno virtual.
    echo Crea con: python -m venv venv ^&^& venv\Scripts\activate ^&^& pip install -r requirements.txt
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo [OK] Entorno virtual activado
echo [OK] Iniciando SISCA en http://localhost:8080 ...
echo.
echo   Login:  http://localhost:8080/login
echo   Admin:  admin@politecnico.edu.co / Admin2026!
echo.
echo   Ctrl+C para detener.
echo ═══════════════════════════════════════════════════════════
echo.

start /b cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8080"

python run.py

echo.
echo Servidor SISCA detenido.
pause
