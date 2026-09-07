@echo off
chcp 65001 >nul 2>&1
title Publicar en INGFRANCISCOVICENT/SIIHAPI-SISCA.PROYECTOINVESTIGATIVO
color 0A
cd /d "%~dp0"

echo.
echo  ═══════════════════════════════════════════════════════════
echo     PUBLICAR EN EL REPOSITORIO "PROYECTOINVESTIGATIVO"
echo  ═══════════════════════════════════════════════════════════
echo.

if not exist ".git" (
    color 0C
    echo [ERROR] Este directorio no es un repositorio de Git.
    pause
    exit /b 1
)

:: ── Paso 1: limpiar los .lock que quedaron de una sesión anterior ──
:: El commit se preparó desde un entorno Linux montado sobre OneDrive, que no
:: permite borrar archivos. Git dejó sus archivos de bloqueo y objetos
:: temporales sin limpiar; desde Windows sí se pueden eliminar.
echo [1/4] Limpiando archivos de bloqueo de Git...
if exist ".git\index.lock" del /f /q ".git\index.lock"
if exist ".git\HEAD.lock" del /f /q ".git\HEAD.lock"
if exist ".git\config.lock" del /f /q ".git\config.lock"
if exist ".git\objects\maintenance.lock" del /f /q ".git\objects\maintenance.lock"
for /r ".git\objects" %%F in (tmp_obj_*) do del /f /q "%%F"
echo     Listo.

:: ── Paso 2: asegurar que el remote apunte al repo correcto ──
echo.
echo [2/4] Verificando el remote "investigativo"...
git remote get-url investigativo >nul 2>&1
if errorlevel 1 (
    git remote add investigativo https://github.com/INGFRANCISCOVICENT/SIIHAPI-SISCA.PROYECTOINVESTIGATIVO.git
    echo     Remote agregado.
) else (
    git remote set-url investigativo https://github.com/INGFRANCISCOVICENT/SIIHAPI-SISCA.PROYECTOINVESTIGATIVO.git
    echo     Remote ya existía, URL confirmada.
)

:: ── Paso 3: mostrar qué se va a subir ──
echo.
echo [3/4] Commits pendientes de subir:
git log --oneline -5
echo.
echo     Archivos sin registrar (si hay alguno):
git status -s
echo.

set /p confirm="¿Subir a GitHub? (S/N): "
if /i not "%confirm%"=="S" (
    echo [INFO] Operación cancelada.
    pause
    exit /b 0
)

:: Si quedaron cambios sin registrar, se agregan ahora
git diff --quiet && git diff --cached --quiet
if errorlevel 1 (
    git add -A
    git commit -m "Actualizacion del proyecto SISCA-SIIHAPI"
)

:: ── Paso 4: push ──
echo.
echo [4/4] Subiendo a GitHub...
echo     Si es la primera vez, se abrirá el navegador para autenticarte.
echo.
git push -u investigativo main

if errorlevel 1 (
    color 0C
    echo.
    echo [ERROR] El push falló. Causas más comunes:
    echo.
    echo   · No tenés permiso de escritura en
    echo     INGFRANCISCOVICENT/SIIHAPI-SISCA.PROYECTOINVESTIGATIVO.
    echo     Pedí que te agreguen como colaborador, o hacé un fork.
    echo.
    echo   · El repositorio remoto ya tiene commits distintos. En ese caso:
    echo       git pull --rebase investigativo main
    echo       git push investigativo main
    echo.
    echo   · Credenciales vencidas. Borralas y reintentá:
    echo       cmdkey /delete:git:https://github.com
    echo.
) else (
    echo.
    echo ═══════════════════════════════════════════════════════════
    echo   PUBLICADO CON ÉXITO
    echo   https://github.com/INGFRANCISCOVICENT/SIIHAPI-SISCA.PROYECTOINVESTIGATIVO
    echo ═══════════════════════════════════════════════════════════
)
echo.
pause
