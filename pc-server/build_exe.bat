@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] No existe .venv en pc-server. Ejecuta primero setup_and_run.bat.
    exit /b 1
)

".venv\Scripts\python.exe" -m pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Instalando PyInstaller en .venv ...
    ".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet pyinstaller
)

echo Empaquetando QuickDropLAN.exe autocontenido (--onefile --noconsole)...
".venv\Scripts\pyinstaller.exe" ^
    --noconfirm ^
    --clean ^
    --onefile ^
    --noconsole ^
    --name QuickDropLAN ^
    --icon "assets\quickdrop.ico" ^
    --add-data "web;web" ^
    --add-data "assets;assets" ^
    --hidden-import "uvicorn.logging" ^
    --hidden-import "uvicorn.loops" ^
    --hidden-import "uvicorn.loops.auto" ^
    --hidden-import "uvicorn.protocols" ^
    --hidden-import "uvicorn.protocols.http" ^
    --hidden-import "uvicorn.protocols.http.auto" ^
    --hidden-import "uvicorn.protocols.http.h11_impl" ^
    --hidden-import "uvicorn.protocols.websockets" ^
    --hidden-import "uvicorn.protocols.websockets.auto" ^
    --hidden-import "uvicorn.lifespan" ^
    --hidden-import "uvicorn.lifespan.on" ^
    --hidden-import "anyio._backends._asyncio" ^
    --hidden-import "pystray._win32" ^
    --hidden-import "zeroconf._utils.ipaddress" ^
    --hidden-import "zeroconf._handlers.answers" ^
    --hidden-import "winotify" ^
    --hidden-import "pyperclip" ^
    --hidden-import "python_multipart" ^
    --hidden-import "multipart" ^
    tray_app.py

if errorlevel 1 (
    echo [ERROR] Fallo el empaquetado con PyInstaller.
    exit /b 1
)

echo.
echo Listo! Ejecutable portable generado en: %~dp0dist\QuickDropLAN.exe
exit /b 0
