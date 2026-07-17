@echo off
title SISCA Mobile - Instalacion Completa
cd /d "%~dp0"

cls
echo.
echo ========================================
echo  SISCA MOBILE - INSTALACION COMPLETA
echo  Politecnico Internacional
echo ========================================
echo.
echo Se ejecutaran 4 pasos. Cada uno mostrara
echo una ventana propia. Cierrala cuando termine
echo y se ejecutara la siguiente automaticamente.
echo.
echo Si en algun paso ves errores rojos:
echo  - NO CIERRES la ventana
echo  - Hazle foto con el celular
echo  - Mandasela al asistente
echo.
pause

start /wait "" cmd /c PASO_1_verificar.bat
start /wait "" cmd /c PASO_2_instalar.bat
start /wait "" cmd /c PASO_3_android.bat
start /wait "" cmd /c PASO_4_abrir_android.bat

echo.
echo TODOS LOS PASOS TERMINADOS
echo.
pause
