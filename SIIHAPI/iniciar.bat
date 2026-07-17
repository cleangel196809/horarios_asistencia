@echo off
title SIIHAPI - Servidor
color 0E
cd /d "%~dp0backend"

echo.
echo ===============================================================
echo   SIIHAPI v1.0 - Politecnico Internacional
echo ===============================================================
echo.

if not exist venv\Scripts\activate.bat (
    color 0C
    echo [ERROR] No hay venv. Ejecuta setup.bat primero.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

REM Siempre usar settings de produccion (Oracle)
set DJANGO_SETTINGS_MODULE=siihapi.settings

REM Verificar conexion Oracle
python -c "import oracledb; oracledb.connect(user='SIIHAPI', password='siihapi_2026', dsn='localhost:1521/XEPDB1').close()" >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [ERROR] No se puede conectar a Oracle XE en localhost:1521
    echo Verifica que Oracle XE este corriendo: lsnrctl status
    echo.
    echo Si quieres correr sin Oracle, edita manualmente settings.py
    echo y cambia ENGINE a django.db.backends.sqlite3
    pause
    exit /b 1
) else (
    color 0A
    echo [OK] Oracle XE 21c conectado.
)

echo.
echo Aplicando migraciones pendientes...
python manage.py migrate --noinput >nul 2>&1

echo.
echo ===============================================================
echo   SERVIDOR INICIANDO
echo ===============================================================
echo.
echo   Login:    http://localhost:8000/login/
echo   Dashboard:http://localhost:8000/dashboard/
echo   API Docs: http://localhost:8000/api/docs/
echo   Admin:    http://localhost:8000/admin/
echo.
echo   Credenciales:
echo     admin@pi.edu.co       / Admin2026!         (ADMIN)
echo     coord@pi.edu.co       / Coord2026!         (COORDINADOR)
echo     docente@pi.edu.co     / Docente2026!       (DOCENTE)
echo     estudiante@pi.edu.co  / Estudiante2026!    (ESTUDIANTE)
echo.
echo   Ctrl+C para detener.
echo ===============================================================
echo.

python manage.py runserver 0.0.0.0:8000

echo.
echo Servidor detenido.
pause
