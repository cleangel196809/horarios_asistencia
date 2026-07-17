@echo off
chcp 65001 >nul
title Limpieza · SISCA + SIIHAPI

cd /d "%~dp0"

echo.
echo ═══════════════════════════════════════════════════════════
echo   LIMPIEZA DE ARCHIVOS BASURA · SISCA + SIIHAPI
echo ═══════════════════════════════════════════════════════════
echo.
echo Esto eliminara:
echo   - Carpetas __pycache__
echo   - Archivos .pyc, .pyo
echo   - Archivos .bak, .tmp, .old
echo.
echo NO se eliminan:
echo   - venv/ (entornos virtuales)
echo   - .env (credenciales)
echo   - node_modules (Mobile)
echo.

set /p confirm="¿Continuar? (S/N): "
if /i not "%confirm%"=="S" (
    echo Cancelado.
    pause
    exit /b 0
)

echo.
echo [1/3] Eliminando __pycache__...
for /d /r %%i in (__pycache__) do (
    if exist "%%i" rd /s /q "%%i" 2>nul
)

echo [2/3] Eliminando .pyc / .pyo...
del /s /q /f *.pyc 2>nul
del /s /q /f *.pyo 2>nul

echo [3/3] Eliminando .bak / .tmp / .old...
del /s /q /f *.bak 2>nul
del /s /q /f *.tmp 2>nul
del /s /q /f *.old 2>nul
del /s /q /f *.orig 2>nul

echo.
echo ═══════════════════════════════════════════════════════════
echo   LIMPIEZA COMPLETADA
echo ═══════════════════════════════════════════════════════════
echo.
pause
