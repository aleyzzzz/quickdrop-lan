"""QuickDrop LAN PC entrypoint with Windows system tray icon (pystray) and headless mode."""

from __future__ import annotations

import argparse
import gc
import logging
import os
import sys
import threading
import time
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
    setup_logging,
)
from server import create_app

logger = logging.getLogger("quickdrop.tray")


def _build_tray_icon_image():
    """Generate a crisp, tiny 64x64 QuickDrop icon in memory with Pillow."""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded dark badge with electric cyan accent arrow/bolt
    draw.rounded_rectangle((4, 4, 60, 60), radius=16, fill=(11, 15, 23, 255), outline=(56, 189, 248, 255), width=3)
    # Up/down transfer chevrons
    draw.polygon([(22, 27), (32, 14), (42, 27), (36, 27), (36, 36), (28, 36), (28, 27)], fill=(56, 189, 248, 255))
    draw.polygon([(22, 39), (32, 51), (42, 39), (36, 39), (36, 33), (28, 33), (28, 39)], fill=(45, 212, 191, 255))
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
    """Save a small PNG icon once for Windows toast notifications."""
    icon_file = data_dir / "quickdrop_icon.png"
    if icon_file.exists():
        return icon_file
    try:
        img = _build_tray_icon_image()
        img.save(icon_file, format="PNG")
        img.close()
        return icon_file
    except Exception as exc:
        logger.warning("No se pudo generar icono PNG: %s", exc)
        return None


def _run_tray(
    *,
    uvicorn_server: uvicorn.Server,
    server_thread: threading.Thread,
    settings_manager: SettingsManager,
) -> None:
    import pystray

    port = settings_manager.settings.port
    local_url = f"http://localhost:{port}"

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
        port=settings_manager.settings.port,
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
