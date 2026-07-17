@echo off
title SIIHAPI - Reset Credenciales
color 0E
cd /d "%~dp0backend"

echo.
echo ===============================================================
echo   SIIHAPI - RESET DE CREDENCIALES
echo ===============================================================
echo.
echo Esto:
echo   1. Detecta si estas en Oracle o SQLite
echo   2. Borra los 4 usuarios principales si existen
echo   3. Los recrea con las passwords correctas
echo   4. Verifica que el login funcione
echo.
echo Los 4 usuarios:
echo   admin@pi.edu.co       / Admin2026!
echo   coord@pi.edu.co       / Coord2026!
echo   docente@pi.edu.co     / Docente2026!
echo   estudiante@pi.edu.co  / Estudiante2026!
echo.
pause

if not exist venv\Scripts\activate.bat (
    color 0C
    echo [ERROR] No hay venv. Ejecuta setup.bat primero.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

python ..\scripts\reset_credenciales.py

echo.
echo ===============================================================
echo Si todos los usuarios dicen [OK]:
echo   1. Cierra el servidor (Ctrl+C en su ventana)
echo   2. Doble clic en iniciar.bat
echo   3. Login en http://localhost:8000/login/
echo ===============================================================
echo.
pause
