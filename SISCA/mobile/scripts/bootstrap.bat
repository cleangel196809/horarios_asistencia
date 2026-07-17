@echo off
REM Bootstrap SISCA Mobile (Windows)
cd /d "%~dp0\.."

echo Instalando dependencias...
call npm install
if errorlevel 1 goto :err

echo Anadiendo plataforma Android...
call npx cap add android

echo Generando iconos y splash...
call npx capacitor-assets generate

echo Sincronizando...
call npx cap sync

echo.
echo === Listo ===
echo Proximos pasos:
echo   npx cap open android    (Para Android Studio)
echo.
echo Nota: iOS solo se puede compilar desde macOS.
pause
exit /b 0

:err
echo Error durante el bootstrap.
pause
exit /b 1
