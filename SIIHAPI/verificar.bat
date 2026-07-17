@echo off
title SIIHAPI - Verificacion completa (Smoke Test)
color 0E
cd /d "%~dp0backend"

echo.
echo ===============================================================
echo   SIIHAPI - SMOKE TEST INTEGRAL
echo ===============================================================
echo.
echo Ejecuto las pruebas que haria un QA senior:
echo.
echo   1. Django check (modelos, settings)
echo   2. Reverse de TODAS las URLs
echo   3. Existencia de TODOS los templates
echo   4. Middleware (anti AssertionError)
echo   5. Imports de modelos
echo   6. Motor IA (CSP + LLM)
echo   7. Carga masiva
echo   8. Datos en BD
echo   9. Login de los 4 usuarios principales
echo.
pause

if not exist venv\Scripts\activate.bat (
    color 0C
    echo [ERROR] No hay venv. Ejecuta setup.bat primero.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

python ..\scripts\smoke_test.py
set RESULT=%errorlevel%

echo.
if %RESULT%==0 (
    color 0A
    echo.
    echo ===============================================================
    echo   TODO BIEN - PUEDES ARRANCAR iniciar.bat
    echo ===============================================================
) else (
    color 0C
    echo.
    echo ===============================================================
    echo   HAY FALLOS - REVISA EL DETALLE ARRIBA
    echo ===============================================================
)
echo.
pause
