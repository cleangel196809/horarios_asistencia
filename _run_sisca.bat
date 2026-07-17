@echo off
title SISCA - Flask 8080
cd /d "%~dp0SISCA"

echo ============================================================
echo   SISCA - Politecnico Internacional
echo   http://localhost:8080
echo ============================================================
echo.

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] No existe el entorno virtual de SISCA.
    echo         Ejecuta iniciar_todo.bat una vez para crearlo.
    echo.
    pause
    exit /b 1
)

if not exist "run.py" (
    echo [ERROR] No se encuentra run.py en %CD%
    pause
    exit /b 1
)

echo [OK] Iniciando Flask con el python del entorno virtual...
echo     (Si Oracle no esta corriendo, SISCA igual abre, pero sin datos)
echo.

REM Abrir el navegador a los ~5s, en segundo plano
start /b cmd /c "ping -n 6 127.0.0.1 >nul & start http://localhost:8080"

REM Ejecutar SISCA con el python del venv (no depende de activate)
"venv\Scripts\python.exe" run.py

echo.
echo ============================================================
echo   SISCA se detuvo. Revisa los mensajes de error de arriba.
echo ============================================================
pause
