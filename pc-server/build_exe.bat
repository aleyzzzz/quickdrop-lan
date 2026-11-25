@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Ejecuta primero setup_and_run.bat para crear el entorno virtual.
    pause
    exit /b 1
)

echo Instalando PyInstaller en .venv ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet pyinstaller

echo Empaquetando QuickDropLAN.exe (--onefile --noconsole)...
".venv\Scripts\pyinstaller.exe" ^
    --noconfirm ^
    --onefile ^
    --noconsole ^
    --name QuickDropLAN ^
    --add-data "web;web" ^
    --hidden-import "pystray._win32" ^
    --hidden-import "zeroconf._utils.ipaddress" ^
    --hidden-import "zeroconf._handlers.answers" ^
    tray_app.py

if errorlevel 1 (
    echo [ERROR] Fallo el empaquetado con PyInstaller.
    pause
    exit /b 1
)

echo.
echo Listo! Ejecutable generado en: %~dp0dist\QuickDropLAN.exe
pause
