@echo off
title SIIHAPI - Migracion Fase 2 (Postgres / integracion_pi)
color 0E
cd /d "%~dp0"

echo.
echo ===============================================================
echo   SIIHAPI - FASE 2: migrar de Oracle a integracion_pi (Postgres)
echo   Politecnico Internacional
echo ===============================================================
echo.
echo Pre-requisitos (deberias tenerlos ya listos):
echo   - Python 3.11+ instalado
echo   - Postgres local corriendo, base "integracion_pi" ya creada
echo   - alter_integracion_pi_fase2.sql YA aplicado en pgAdmin
echo   - backend\.env con POSTGRES_PASSWORD puesta (tu password real)
echo.
pause

REM ────────────────────────────────────────────────────────────────
REM  PASO 1 - venv + dependencias (incluye psycopg para Postgres)
REM ────────────────────────────────────────────────────────────────
echo.
echo --- PASO 1/2: Entorno virtual y dependencias ---
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

REM ────────────────────────────────────────────────────────────────
REM  PASO 2 - Migraciones Django (solo crea SIIHAPI_MATRICULA y
REM  SIIHAPI_HORARIO - el resto de tablas ya existen en integracion_pi
REM  y los modelos les apuntan con managed=False, no las toca)
REM ────────────────────────────────────────────────────────────────
echo.
echo --- PASO 2/2: Aplicando migraciones Django ---
python manage.py migrate
if errorlevel 1 (
    color 0C
    echo [ERROR] Fallo migrate. Revisa el detalle arriba:
    echo   - Si dice "Connection refused": Postgres no esta corriendo.
    echo   - Si dice "password authentication failed": revisa
    echo     POSTGRES_PASSWORD en backend\.env.
    echo   - Si dice "database integracion_pi does not exist": crea la
    echo     base en pgAdmin primero.
    pause
    exit /b 1
)

color 0A
echo.
echo ===============================================================
echo   MIGRACION FASE 2 COMPLETA
echo ===============================================================
echo.
echo SIIHAPI ahora corre sobre integracion_pi (Postgres) en vez de
echo Oracle. Las cuentas reales de docentes/usuarios que ya cargamos
echo en integracion_pi funcionan directo, sin nada mas que hacer.
echo.
echo Para probar:
echo   1. python manage.py runserver
echo   2. Abre http://localhost:8000/login/
echo.
pause
