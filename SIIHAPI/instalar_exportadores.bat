@echo off
title SIIHAPI - Instalar exportadores (Word + PowerPoint)
color 0E
cd /d "%~dp0backend"

echo.
echo ===============================================================
echo   SIIHAPI - INSTALADOR DE EXPORTADORES
echo ===============================================================
echo.
echo Instala las librerias para descargar auditoria como:
echo   - Excel  (openpyxl, ya viene)
echo   - PDF    (reportlab, ya viene)
echo   - Word   (python-docx, NUEVO)
echo   - PowerPoint (python-pptx, NUEVO)
echo.
pause

if not exist venv\Scripts\activate.bat (
    color 0C
    echo [ERROR] No hay venv. Ejecuta setup.bat primero.
    pause
    exit /b 1
)
call venv\Scripts\activate.bat

echo.
echo Instalando python-docx (Word)...
pip install python-docx

echo.
echo Instalando python-pptx (PowerPoint)...
pip install python-pptx

echo.
echo Verificando todo...
python -c "import openpyxl; print('  [OK] openpyxl (Excel)')"
python -c "import reportlab; print('  [OK] reportlab (PDF)')"
python -c "import docx; print('  [OK] python-docx (Word)')"
python -c "import pptx; print('  [OK] python-pptx (PowerPoint)')"

color 0A
echo.
echo ===============================================================
echo   EXPORTADORES INSTALADOS
echo ===============================================================
echo.
echo Ahora reinicia el servidor (iniciar.bat) y entra como ADMIN.
echo En el panel Auditoria veras los 4 botones de descarga.
echo.
pause
