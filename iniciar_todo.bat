@echo off
chcp 65001 >nul 2>&1
title SISCA + SIIHAPI
color 0B
cd /d "%~dp0"

echo.
echo  +----------------------------------------------------------+
echo  ^|   SISCA + SIIHAPI - Politecnico Internacional           ^|
echo  +----------------------------------------------------------+
echo.

:: Verificar Python
python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo  [ERROR] Python no encontrado en PATH.
    pause
    exit /b 1
)
echo  [OK] Python OK

:: Crear venv SISCA si no existe
if not exist "SISCA\venv\Scripts\activate.bat" (
    echo  [INFO] Instalando dependencias SISCA por primera vez...
    cd /d "%~dp0SISCA"
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt -q
    deactivate
    cd /d "%~dp0"
    echo  [OK] venv SISCA creado
)

:: Crear venv SIIHAPI si no existe
if not exist "SIIHAPI\backend\venv\Scripts\activate.bat" (
    echo  [INFO] Instalando dependencias SIIHAPI por primera vez...
    cd /d "%~dp0SIIHAPI\backend"
    python -m venv venv
    call venv\Scripts\activate.bat
    pip install -r requirements.txt -q
    deactivate
    cd /d "%~dp0"
    echo  [OK] venv SIIHAPI creado
)

echo.
echo  Abriendo SISCA y SIIHAPI...
echo.

start "SISCA Flask 8080" "%~dp0_run_sisca.bat"
timeout /t 2 /nobreak >nul
start "SIIHAPI Django 8000" "%~dp0_run_siihapi.bat"

echo  [OK] Ventanas abiertas. Esperando 10 segundos...
timeout /t 10 /nobreak >nul

start http://localhost:8080
timeout /t 1 /nobreak >nul
start http://localhost:8000

echo.
echo  SISCA   : http://localhost:8080  (admin@politecnico.edu.co / Admin2026!)
echo  SIIHAPI : http://localhost:8000  (admin@pi.edu.co / Admin2026!)
echo.
echo  Para detener: cierra las 2 ventanas de consola.
echo.
pause
