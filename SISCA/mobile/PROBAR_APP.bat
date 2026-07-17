@echo off
title SISCA Mobile - Vista previa
cd /d "%~dp0\www"

echo.
echo ========================================
echo  SISCA MOBILE - VISTA PREVIA EN CHROME
echo ========================================
echo.
echo Esto va a:
echo  1. Iniciar un mini-servidor
echo  2. Abrir Chrome con la app en modo movil
echo.
echo Para cerrar: vuelve aqui y presiona Ctrl+C
echo.
pause

start "" cmd /c "timeout /t 2 /nobreak > nul && start chrome --new-window --window-size=420,840 http://localhost:8765/"

echo.
echo Servidor en http://localhost:8765/
echo Abriendo Chrome...
echo.

python -m http.server 8765 2>nul
if errorlevel 1 (
  py -m http.server 8765 2>nul
)
pause
