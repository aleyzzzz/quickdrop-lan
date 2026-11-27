"""QuickDrop LAN PC entrypoint with Windows system tray icon, single-instance guard, and autostart toggle."""

from __future__ import annotations

import argparse
import gc
import logging
import os
import shutil
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

import uvicorn

from config import (
    APP_NAME,
    DEFAULT_PORT,
    SettingsManager,
    build_uvicorn_log_config,
    get_default_data_dir,
    get_primary_lan_ip,
    get_resource_dir,
    is_frozen,
    setup_logging,
)
from server import create_app

logger = logging.getLogger("quickdrop.tray")

_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE_NAME = "QuickDropLAN"


def _build_tray_icon_image():
    """Load bundled PNG icon from resources (MEIPASS-aware) or draw a crisp 64x64 fallback."""
    from PIL import Image, ImageDraw

    bundled_png = get_resource_dir() / "assets" / "quickdrop.png"
    if bundled_png.is_file():
        try:
            with Image.open(bundled_png) as opened:
                return opened.convert("RGBA").resize((64, 64), Image.Resampling.LANCZOS)
        except Exception as exc:
            logger.warning("No se pudo cargar icono empaquetado (%s), usando fallback: %s", bundled_png, exc)

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded obsidian badge with cyan/emerald transfer chevrons
    draw.rounded_rectangle((4, 4, 60, 60), radius=16, fill=(9, 9, 11, 255), outline=(6, 182, 212, 255), width=3)
    draw.polygon([(22, 27), (32, 14), (42, 27), (36, 27), (36, 36), (28, 36), (28, 27)], fill=(34, 211, 238, 255))
    draw.polygon([(22, 39), (32, 51), (42, 39), (36, 39), (36, 33), (28, 33), (28, 39)], fill=(16, 185, 129, 255))
    return img


def _trim_process_memory() -> None:
    """Reclaim unused startup/import pages so idle RAM stays minimal on Windows."""
    gc.collect()
    if os.name == "nt":
        try:
            import ctypes

            handle = ctypes.windll.kernel32.GetCurrentProcess()
            ctypes.windll.kernel32.SetProcessWorkingSetSize(handle, -1, -1)
        except Exception:
            pass


def _ensure_icon_file(data_dir: Path) -> Path | None:
    """Ensure a persistent PNG icon exists in %APPDATA%\\QuickDropLAN for Windows toast notifications."""
    icon_file = data_dir / "quickdrop_icon.png"
    if icon_file.exists():
        return icon_file
    bundled_png = get_resource_dir() / "assets" / "quickdrop.png"
    if bundled_png.is_file():
        try:
            shutil.copyfile(bundled_png, icon_file)
            return icon_file
        except OSError:
            pass
    try:
        img = _build_tray_icon_image()
        img.save(icon_file, format="PNG")
        img.close()
        return icon_file
    except Exception as exc:
        logger.warning("No se pudo generar icono PNG: %s", exc)
        return None


def _is_instance_already_running(port: int) -> bool:
    """Check if QuickDrop LAN is already listening locally on the configured port."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=0.45) as resp:
            return resp.status == 200
    except Exception:
        pass

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.35)
    try:
        return sock.connect_ex(("127.0.0.1", port)) == 0
    except OSError:
        return False
    finally:
        sock.close()


def _get_autostart_command() -> str:
    """Return the command line registered in HKCU\\...\\Run for Windows startup."""
    if is_frozen():
        return f'"{Path(sys.executable).resolve()}"'
    exe_path = Path(sys.executable).resolve()
    pythonw = exe_path.with_name("pythonw.exe")
    launcher = pythonw if pythonw.is_file() else exe_path
    return f'"{launcher}" "{Path(__file__).resolve()}"'


def _is_autostart_enabled() -> bool:
    """Return True if QuickDropLAN is registered to start with Windows for current user."""
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, _RUN_VALUE_NAME)
            return bool(str(val).strip())
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _set_autostart_enabled(enable: bool) -> bool:
    """Enable or disable automatic startup via HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""
    if os.name != "nt":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                cmd = _get_autostart_command()
                winreg.SetValueEx(key, _RUN_VALUE_NAME, 0, winreg.REG_SZ, cmd)
                logger.info("Inicio con Windows activado: %s", cmd)
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE_NAME)
                    logger.info("Inicio con Windows desactivado.")
                except FileNotFoundError:
                    pass
        return True
    except OSError as exc:
        logger.warning("No se pudo actualizar inicio con Windows: %s", exc)
        return False


def _run_tray(
    *,
    uvicorn_server: uvicorn.Server,
    server_thread: threading.Thread,
    settings_manager: SettingsManager,
) -> None:
    import pystray

    port = settings_manager.settings.port
    local_url = f"http://127.0.0.1:{port}"

    def open_web_ui(_icon=None, _item=None) -> None:
        webbrowser.open(local_url)

    def copy_lan_url(_icon=None, _item=None) -> None:
        lan_url = f"http://{get_primary_lan_ip()}:{port}"
        try:
            import pyperclip

            pyperclip.copy(lan_url)
        except Exception as exc:
            logger.warning("Error copiando URL LAN: %s", exc)

    def open_downloads(_icon=None, _item=None) -> None:
        folder = settings_manager.settings.resolved_download_dir()
        if os.name == "nt":
            os.startfile(str(folder))

    def toggle_auto_copy(_icon, _item) -> None:
        current = settings_manager.settings.auto_copy_clipboard
        settings_manager.update(auto_copy_clipboard=not current)

    def toggle_notifications(_icon, _item) -> None:
        current = settings_manager.settings.notifications_enabled
        settings_manager.update(notifications_enabled=not current)

    def toggle_autostart(_icon, _item) -> None:
        _set_autostart_enabled(not _is_autostart_enabled())

    def quit_app(icon, _item=None) -> None:
        logger.info("Cerrando QuickDrop LAN desde la bandeja...")
        uvicorn_server.should_exit = True
        icon.stop()

    icon_image = _build_tray_icon_image()
    menu = pystray.Menu(
        pystray.MenuItem(f"Abrir QuickDrop ({local_url})", open_web_ui, default=True),
        pystray.MenuItem(
            lambda _item: f"Copiar URL LAN (http://{get_primary_lan_ip()}:{port})",
            copy_lan_url,
        ),
        pystray.MenuItem("Abrir carpeta de descargas", open_downloads),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(
            "Copiar links/texto al portapapeles",
            toggle_auto_copy,
            checked=lambda _item: settings_manager.settings.auto_copy_clipboard,
        ),
        pystray.MenuItem(
            "Notificaciones de Windows",
            toggle_notifications,
            checked=lambda _item: settings_manager.settings.notifications_enabled,
        ),
        pystray.MenuItem(
            "Iniciar con Windows",
            toggle_autostart,
            checked=lambda _item: _is_autostart_enabled(),
        ),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Salir", quit_app),
    )

    tray_icon = pystray.Icon(
        name="quickdrop_lan",
        icon=icon_image,
        title=f"{APP_NAME} — http://{get_primary_lan_ip()}:{port}",
        menu=menu,
    )

    _trim_process_memory()
    tray_icon.run()
    uvicorn_server.should_exit = True
    server_thread.join(timeout=5.0)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="QuickDrop LAN — Servidor local ultrarrápido")
    parser.add_argument("--host", default=None, help="Interfaz de escucha (por defecto 0.0.0.0)")
    parser.add_argument("--port", type=int, default=None, help=f"Puerto HTTP (por defecto {DEFAULT_PORT})")
    parser.add_argument("--download-dir", default=None, help="Carpeta destino para archivos recibidos")
    parser.add_argument("--data-dir", default=None, help="Carpeta para historial, config y logs")
    parser.add_argument("--headless", action="store_true", help="Ejecutar sin ícono en la bandeja del sistema")
    parser.add_argument("--no-mdns", action="store_true", help="Desactivar anuncio mDNS/Zeroconf")
    parser.add_argument("--no-notifications", action="store_true", help="Desactivar toasts de Windows")
    parser.add_argument("--verbose", action="store_true", help="Habilitar logs detallados")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    data_dir = Path(args.data_dir).expanduser().resolve() if args.data_dir else get_default_data_dir()
    log_file = setup_logging(data_dir, verbose=args.verbose)

    overrides = {
        "host": args.host,
        "port": args.port,
        "download_dir": str(Path(args.download_dir).expanduser().resolve()) if args.download_dir else None,
    }
    settings_manager = SettingsManager(data_dir=data_dir, overrides=overrides)
    port = settings_manager.settings.port

    # Smart single-instance guard: if already running, open web UI and exit cleanly
    if not args.headless and _is_instance_already_running(port):
        local_url = f"http://127.0.0.1:{port}"
        logger.info("QuickDrop LAN ya está ejecutándose en el puerto %d; abriendo %s", port, local_url)
        webbrowser.open(local_url)
        return 0

    icon_file = None if args.no_notifications else _ensure_icon_file(data_dir)

    app = create_app(
        settings_manager,
        enable_mdns=not args.no_mdns,
        enable_notifications=not args.no_notifications,
        icon_path=icon_file,
    )

    uvicorn_config = uvicorn.Config(
        app=app,
        host=settings_manager.settings.host,
        port=port,
        log_config=build_uvicorn_log_config(log_file),
        access_log=False,
        timeout_keep_alive=30,
        limit_concurrency=64,
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    if args.headless:
        _trim_process_memory()
        uvicorn_server.run()
        return 0

    server_thread = threading.Thread(
        target=uvicorn_server.run,
        name="quickdrop-uvicorn",
        daemon=True,
    )
    server_thread.start()

    # Wait briefly for uvicorn startup before showing tray icon
    deadline = time.monotonic() + 5.0
    while not uvicorn_server.started and server_thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)

    try:
        _run_tray(
            uvicorn_server=uvicorn_server,
            server_thread=server_thread,
            settings_manager=settings_manager,
        )
    except KeyboardInterrupt:
        uvicorn_server.should_exit = True
        server_thread.join(timeout=5.0)
    except Exception as exc:
        logger.exception("Fallo en el ícono de bandeja (%s). Manteniendo servidor activo.", exc)
        server_thread.join()

    return 0


if __name__ == "__main__":
    sys.exit(main())
