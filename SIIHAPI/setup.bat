@echo off
title SIIHAPI - Instalacion Completa
color 0E
cd /d "%~dp0"

echo.
echo ===============================================================
echo   SIIHAPI v1.0 - INSTALACION COMPLETA
echo   Politecnico Internacional
echo ===============================================================
echo.
echo Este unico script hace TODA la instalacion:
echo.
echo   1. Verifica/instala dependencias Python
echo   2. Verifica/crea el esquema SIIHAPI en Oracle XE 21c
echo   3. Aplica las migraciones
echo   4. Carga datos reales (3 sedes, 135 salones, 27 programas)
echo.
echo Pre-requisitos:
echo   - Python 3.11+ instalado
echo   - Oracle XE 21c instalado y corriendo
echo.
pause

REM ────────────────────────────────────────────────────────────────
REM  PASO 1 - venv + dependencias
REM ────────────────────────────────────────────────────────────────
echo.
echo --- PASO 1/4: Entorno virtual y dependencias ---
cd backend
if not exist venv (
    echo Creando venv...
    python -m venv venv
    if errorlevel 1 (
        color 0C
        echo [ERROR] No se pudo crear venv. Verifica que Python este instalado.
        pause
        exit /b 1
    )
)
call venv\Scripts\activate.bat

echo Instalando dependencias (puede tardar varios minutos)...
pip install --upgrade pip --quiet
pip install -r requirements.txt
if errorlevel 1 (
    color 0C
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas.
cd ..

REM ────────────────────────────────────────────────────────────────
REM  PASO 2 - Esquema Oracle SIIHAPI
REM ────────────────────────────────────────────────────────────────
echo.
echo --- PASO 2/4: Esquema Oracle SIIHAPI ---
cd backend
call venv\Scripts\activate.bat
python -c "import oracledb; oracledb.connect(user='SIIHAPI', password='siihapi_2026', dsn='localhost:1521/XEPDB1').close()" >nul 2>&1
if errorlevel 1 (
    echo [INFO] Esquema SIIHAPI no existe. Necesito tu password de SYSTEM.
    echo.
    echo La password de SYSTEM es la que pusiste al instalar Oracle XE 21c.
    set /p SYSPWD=Password de SYSTEM:

    where sqlplus >nul 2>&1
    if errorlevel 1 (
        color 0C
        echo [ERROR] sqlplus no esta en el PATH.
        echo Agrega esta carpeta al PATH del sistema:
        echo    C:\app\^<usuario^>\product\21c\dbhomeXE\bin
        pause
        exit /b 1
    )

    cd ..
    sqlplus -L system/!SYSPWD!@//localhost:1521/XEPDB1 @scripts\01_crear_esquema_oracle.sql
    if errorlevel 1 (
        color 0C
        echo [ERROR] No se pudo crear el esquema. Password incorrecta o Oracle no responde.
        pause
        exit /b 1
    )
    echo [OK] Esquema SIIHAPI creado.
) else (
    echo [OK] Esquema SIIHAPI ya existe.
    cd ..
)

REM ────────────────────────────────────────────────────────────────
REM  PASO 3 - Migraciones Django
REM ────────────────────────────────────────────────────────────────
echo.
echo --- PASO 3/4: Aplicando migraciones Django ---
cd backend
call venv\Scripts\activate.bat
set DJANGO_SETTINGS_MODULE=siihapi.settings

python manage.py makemigrations autenticacion academico infraestructura personal matriculas horarios integracion_sisca >nul
python manage.py migrate
if errorlevel 1 (
    color 0C
    echo [ERROR] Fallo migrate. Revisa el detalle.
    pause
    exit /b 1
)
echo [OK] Migraciones aplicadas.

REM ────────────────────────────────────────────────────────────────
REM  PASO 4 - Datos reales del Politecnico
REM ────────────────────────────────────────────────────────────────
echo.
echo --- PASO 4/4: Cargando datos reales del Politecnico ---
python ..\scripts\02_seed_datos_reales.py
if errorlevel 1 (
    color 0C
    echo [ERROR] Fallo seed datos reales.
    pause
    exit /b 1
)

color 0A
echo.
echo ===============================================================
echo   INSTALACION COMPLETA - SIIHAPI LISTO
echo ===============================================================
echo.
echo Para usar la app:
echo.
echo   1. Doble clic en  iniciar.bat
echo   2. Abre Chrome en http://localhost:8000/login/
echo   3. Entra con cualquiera de estas credenciales:
echo.
echo      ADMIN:       admin@pi.edu.co        / Admin2026!
echo      COORDINADOR: coord@pi.edu.co        / Coord2026!
echo      DOCENTE:     docente@pi.edu.co      / Docente2026!
echo      ESTUDIANTE:  estudiante@pi.edu.co   / Estudiante2026!
echo.
echo Ver README.md para mas detalles.
echo.
pause
