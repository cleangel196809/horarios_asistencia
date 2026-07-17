@echo off
title Abrir Android Studio
cd /d "%~dp0"

echo Abriendo SISCA Mobile en Android Studio...
echo.

call npx cap open android

echo.
pause
