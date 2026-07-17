@echo off
chcp 65001 >nul 2>&1
title Subir Cambios a GitHub
color 0A
cd /d "%~dp0"

echo.
echo  ═══════════════════════════════════════════════════════════
echo     SUBIR CAMBIOS AL REPOSITORIO DE GITHUB
echo  ═══════════════════════════════════════════════════════════
echo.

:: Verificar si es un repositorio git
if not exist ".git" (
    color 0C
    echo [ERROR] Este directorio no es un repositorio de Git.
    pause
    exit /b 1
)

:: Mostrar estado actual
echo [+] Estado de los archivos:
git status -s
echo.

:: Preguntar por confirmación
set /p confirm="¿Quieres registrar y subir estos cambios? (S/N): "
if /i not "%confirm%"=="S" (
    echo [INFO] Operación cancelada.
    pause
    exit /b 0
)

:: Agregar todos los cambios
echo.
echo [1/3] Preparando archivos (git add)...
git add .

:: Pedir el mensaje del commit
echo.
set /p commit_msg="[2/3] Ingresa una descripción corta del cambio: "
if "%commit_msg%"=="" (
    set commit_msg="Actualización de archivos y código"
)

:: Hacer el commit
echo.
git commit -m "%commit_msg%"

:: Subir cambios
echo.
echo [3/3] Subiendo cambios a GitHub (git push)...
git push origin main

if errorlevel 1 (
    color 0C
    echo.
    echo [ERROR] Hubo un problema al subir los cambios a GitHub.
    echo         Verifica tu conexión a internet o que tengas permisos de colaborador.
) else (
    echo.
    echo ═══════════════════════════════════════════════════════════
    echo   ¡CAMBIOS SUBIDOS CON ÉXITO!
    echo ═══════════════════════════════════════════════════════════
)
echo.
pause
