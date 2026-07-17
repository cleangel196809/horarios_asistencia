@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion
title POLITECNICO INTERNACIONAL - SISCA + SIIHAPI (Lanzador automatico)
color 0B
cd /d "%~dp0"
set "RAIZ=%~dp0"

echo ============================================================
echo   POLITECNICO INTERNACIONAL
echo   SISCA (Flask 8080) + SIIHAPI (Django 8000)
echo   Lanzador automatico: instala, configura y ejecuta todo
echo ============================================================
echo.

REM =================== 1. PYTHON ===================
echo [1/6] Verificando Python...
set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY ( where python >nul 2>&1 && set "PY=python" )
if not defined PY (
    echo   [!] Python no esta instalado. Intentando instalarlo con winget...
    winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        color 0C
        echo.
        echo   [ERROR] No se pudo instalar Python automaticamente.
        echo           Descargalo de https://www.python.org/downloads/
        echo           IMPORTANTE: marca la casilla "Add Python to PATH" al instalar.
        echo           Luego vuelve a ejecutar este archivo.
        goto :fin
    )
    echo   [OK] Python instalado. Cierra esta ventana y ejecuta INICIAR.bat de nuevo
    echo        para que Windows reconozca Python en el PATH.
    goto :fin
)
for /f "delims=" %%v in ('%PY% --version 2^>^&1') do echo   [OK] %%v detectado.

REM =================== 2. PUERTOS ===================
echo [2/6] Liberando puertos 8080 y 8000 (si estan ocupados)...
call :kill_port 8080
call :kill_port 8000
echo   [OK] Puertos liberados.

REM =================== 3. SISCA (Flask) ===================
echo [3/6] Preparando SISCA (Flask)...
if not exist "%RAIZ%SISCA\venv\Scripts\python.exe" (
    echo   [INFO] Creando entorno virtual de SISCA...
    %PY% -m venv "%RAIZ%SISCA\venv" || goto :err_venv
)
if not exist "%RAIZ%SISCA\venv\.deps_ok" (
    echo   [INFO] Instalando dependencias de SISCA (solo la primera vez)...
    "%RAIZ%SISCA\venv\Scripts\python.exe" -m pip install --upgrade pip -q
    "%RAIZ%SISCA\venv\Scripts\python.exe" -m pip install -r "%RAIZ%SISCA\requirements.txt" -q || goto :err_pip
    echo ok> "%RAIZ%SISCA\venv\.deps_ok"
)
if not exist "%RAIZ%SISCA\.env" (
    echo   [AVISO] No existe SISCA\.env; se copia desde .env.example.
    copy /y "%RAIZ%SISCA\.env.example" "%RAIZ%SISCA\.env" >nul
    set "REVISAR_ENV=1"
)
echo   [OK] SISCA preparado.

REM =================== 4. SIIHAPI (Django) ===================
echo [4/6] Preparando SIIHAPI (Django)...
if not exist "%RAIZ%SIIHAPI\backend\venv\Scripts\python.exe" (
    echo   [INFO] Creando entorno virtual de SIIHAPI...
    %PY% -m venv "%RAIZ%SIIHAPI\backend\venv" || goto :err_venv
)
if not exist "%RAIZ%SIIHAPI\backend\venv\.deps_ok" (
    echo   [INFO] Instalando dependencias de SIIHAPI (solo la primera vez, puede tardar)...
    "%RAIZ%SIIHAPI\backend\venv\Scripts\python.exe" -m pip install --upgrade pip -q
    "%RAIZ%SIIHAPI\backend\venv\Scripts\python.exe" -m pip install -r "%RAIZ%SIIHAPI\backend\requirements.txt" -q || goto :err_pip
    echo ok> "%RAIZ%SIIHAPI\backend\venv\.deps_ok"
)
if not exist "%RAIZ%SIIHAPI\backend\.env" (
    echo   [AVISO] No existe SIIHAPI\backend\.env; se copia desde .env.example.
    copy /y "%RAIZ%SIIHAPI\backend\.env.example" "%RAIZ%SIIHAPI\backend\.env" >nul
    set "REVISAR_ENV=1"
)
echo   [OK] SIIHAPI preparado.

REM =================== 5. MIGRACIONES ===================
echo [5/6] Aplicando migraciones de SIIHAPI...
pushd "%RAIZ%SIIHAPI\backend"
set DJANGO_SETTINGS_MODULE=siihapi.settings
"venv\Scripts\python.exe" manage.py migrate --noinput
if errorlevel 1 (
    echo   [AVISO] Las migraciones no se completaron. Suele ser porque Oracle XE
    echo           no esta iniciado. Inicia el servicio de Oracle y reintenta.
    echo           La aplicacion intentara abrir de todos modos.
) else (
    echo   [OK] Migraciones aplicadas.
)
popd

REM =================== 6. LANZAR ===================
echo [6/6] Iniciando servidores...
start "SISCA - Flask 8080" "%RAIZ%_run_sisca.bat"
timeout /t 3 /nobreak >nul
start "SIIHAPI - Django 8000" "%RAIZ%_run_siihapi.bat"

echo   Esperando a que los servidores levanten (12 s)...
timeout /t 12 /nobreak >nul
start "" http://localhost:8080
timeout /t 1 /nobreak >nul
start "" http://localhost:8000

echo.
echo ============================================================
echo   LISTO - Aplicacion en ejecucion
echo   SISCA   : http://localhost:8080
echo   SIIHAPI : http://localhost:8000
echo ============================================================
if defined REVISAR_ENV (
    echo.
    echo   [IMPORTANTE] Se crearon archivos .env de ejemplo. Si la app no se
    echo   conecta a la base de datos, edita estos archivos con las credenciales
    echo   reales de Oracle y vuelve a ejecutar:
    echo       - SISCA\.env
    echo       - SIIHAPI\backend\.env
)
echo.
echo   Para DETENER la aplicacion: cierra las 2 ventanas de los servidores.
goto :fin

REM =================== SUBRUTINAS ===================
:kill_port
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%~1 " ^| findstr LISTENING') do (
    taskkill /f /pid %%a >nul 2>&1
)
exit /b 0

:err_venv
color 0C
echo.
echo   [ERROR] No se pudo crear el entorno virtual.
echo           Verifica que Python este bien instalado (python --version).
goto :fin

:err_pip
color 0C
echo.
echo   [ERROR] Fallo la instalacion de dependencias (pip).
echo           Revisa tu conexion a Internet y vuelve a ejecutar.
goto :fin

:fin
echo.
pause
endlocal
