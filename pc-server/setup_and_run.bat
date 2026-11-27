@echo off
setlocal enabledelayedexpansion

cd /d "%~dp0"

echo ========================================
echo   QuickDrop LAN - Setup y Arranque PC
echo ========================================

:: Locate Python 3.11+
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] No se encontro Python en el PATH. Instala Python 3.11 o superior.
    pause
    exit /b 1
)

python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo [ERROR] Se requiere Python 3.11 o superior.
    python --version
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [1/3] Creando entorno virtual en .venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo [ERROR] No se pudo crear el entorno virtual.
        pause
        exit /b 1
    )
)

echo [2/3] Verificando e instalando dependencias ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check --quiet -r requirements.txt
if errorlevel 1 (
    echo [ERROR] Fallo la instalacion de dependencias.
    pause
    exit /b 1
)

echo [3/3] Iniciando QuickDrop LAN en la bandeja del sistema (sin consola)...
start "" /b ".venv\Scripts\pythonw.exe" "%~dp0tray_app.py"

echo.
echo QuickDrop LAN ya esta corriendo en segundo plano.
echo - Interfaz web: http://localhost:8765
echo - Haz doble clic en el icono de la bandeja del sistema para abrirlo.
timeout /t 3 /nobreak >nul
exit /b 0
