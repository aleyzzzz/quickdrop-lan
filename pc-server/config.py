"""Configuration, logging, and network helpers for QuickDrop LAN."""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

APP_NAME = "QuickDrop LAN"
APP_VERSION = "1.0.0"
DEFAULT_PORT = 8765
MAX_FILE_SIZE_BYTES = 2 * 1024 * 1024 * 1024  # 2 GiB
STREAM_CHUNK_SIZE = 1024 * 1024  # 1 MiB chunks for low RAM streaming
MAX_HISTORY_ITEMS = 500
MDNS_SERVICE_TYPE = "_quickdrop._tcp.local."
DEFAULT_OUTBOX_TTL_MINUTES = 60
OUTBOX_CLEANUP_INTERVAL_SECONDS = 300.0  # 5 minutes
AFTER_DOWNLOAD_DELETE_DELAY_SECONDS = 120.0  # 2 minutes


def is_frozen() -> bool:
    """Return True when running as a PyInstaller frozen executable."""
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def get_resource_dir() -> Path:
    """Return directory containing bundled assets (supports PyInstaller onefile)."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def get_default_data_dir() -> Path:
    """Return writable per-user directory for settings, history, and logs (%APPDATA%\\QuickDropLAN)."""
    env_dir = os.environ.get("QUICKDROP_DATA_DIR")
    if env_dir:
        path = Path(env_dir).expanduser().resolve()
    else:
        app_data = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA")
        if app_data:
            path = Path(app_data) / "QuickDropLAN"
        else:
            path = Path.home() / ".quickdrop-lan"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_default_download_dir() -> Path:
    """Return default destination folder for received files (~/Downloads/QuickDrop)."""
    env_dir = os.environ.get("QUICKDROP_DOWNLOAD_DIR")
    if env_dir:
        path = Path(env_dir).expanduser().resolve()
    else:
        path = Path.home() / "Downloads" / "QuickDrop"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_default_outbox_dir(data_dir: Path | None = None) -> Path:
    """Return isolated temporary outbox folder (%APPDATA%\\QuickDropLAN\\outbox) for PC -> Phone copies."""
    env_dir = os.environ.get("QUICKDROP_OUTBOX_DIR")
    if env_dir:
        path = Path(env_dir).expanduser().resolve()
    else:
        base = data_dir if data_dir is not None else get_default_data_dir()
        path = base / "outbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class AppSettings:
    port: int = DEFAULT_PORT
    host: str = "0.0.0.0"
    download_dir: str = ""
    outbox_dir: str = ""
    auto_copy_clipboard: bool = True
    notifications_enabled: bool = True
    mdns_enabled: bool = True
    device_name: str = ""
    outbox_ttl_minutes: int = DEFAULT_OUTBOX_TTL_MINUTES
    auto_delete_after_download: bool = True

    def resolved_download_dir(self) -> Path:
        path = Path(self.download_dir) if self.download_dir else get_default_download_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolved_outbox_dir(self, data_dir: Path | None = None) -> Path:
        if self.outbox_dir:
            path = Path(self.outbox_dir).expanduser().resolve()
        else:
            path = get_default_outbox_dir(data_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolved_device_name(self) -> str:
        return self.device_name.strip() or socket.gethostname()


class SettingsManager:
    """Loads and atomically persists QuickDrop LAN settings."""

    def __init__(self, data_dir: Path, overrides: dict[str, Any] | None = None) -> None:
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.data_dir / "settings.json"
        self._overrides = overrides or {}
        self.settings = self._load()

    def download_dir(self) -> Path:
        return self.settings.resolved_download_dir()

    def outbox_dir(self) -> Path:
        return self.settings.resolved_outbox_dir(self.data_dir)

    def _load(self) -> AppSettings:
        raw: dict[str, Any] = {}
        if self.settings_path.exists():
            try:
                raw = json.loads(self.settings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = {}

        valid_fields = {f.name for f in AppSettings.__dataclass_fields__.values()}
        filtered = {k: v for k, v in raw.items() if k in valid_fields}
        for key, value in self._overrides.items():
            if key in valid_fields and value is not None:
                filtered[key] = value
        return AppSettings(**filtered)

    def save(self) -> None:
        tmp_path = self.settings_path.with_suffix(".tmp")
        tmp_path.write_text(
            json.dumps(asdict(self.settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, self.settings_path)

    def update(self, **kwargs: Any) -> AppSettings:
        for key, value in kwargs.items():
            if hasattr(self.settings, key) and value is not None:
                setattr(self.settings, key, value)
        self.save()
        return self.settings


def get_primary_lan_ip() -> str:
    """Detect the primary LAN IPv4 address without sending network traffic."""
    candidates: list[str] = []
    for target in (("192.168.1.1", 80), ("10.255.255.255", 1), ("8.8.8.8", 80)):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(target)
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127.") and ip != "0.0.0.0":
                return ip
        except OSError:
            continue
        finally:
            sock.close()

    try:
        _, _, ips = socket.gethostbyname_ex(socket.gethostname())
        for ip in ips:
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                candidates.append(ip)
    except OSError:
        pass

    return candidates[0] if candidates else "127.0.0.1"


def get_all_lan_ipv4() -> list[str]:
    """Return a deduplicated list of non-loopback IPv4 addresses on this host."""
    primary = get_primary_lan_ip()
    ips: list[str] = []
    if primary and not primary.startswith("127."):
        ips.append(primary)
    try:
        _, _, host_ips = socket.gethostbyname_ex(socket.gethostname())
        for ip in host_ips:
            if (
                ip not in ips
                and not ip.startswith("127.")
                and not ip.startswith("169.254.")
                and ":" not in ip
            ):
                ips.append(ip)
    except OSError:
        pass
    return ips or ["127.0.0.1"]


class IsoFormatter(logging.Formatter):
    """Formatter emitting ISO-8601 timestamps with local timezone offset."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        dt = datetime.fromtimestamp(record.created).astimezone()
        return dt.isoformat(timespec="seconds")


def setup_logging(data_dir: Path, verbose: bool = False) -> Path:
    """Configure file logging (and optional console logging when attached)."""
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "quickdrop_lan.log"

    level = logging.DEBUG if verbose else logging.INFO
    formatter = IsoFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    root = logging.getLogger("quickdrop")
    root.setLevel(level)
    root.handlers.clear()

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Under pythonw.exe / PyInstaller --noconsole, sys.stderr can be None.
    if sys.stderr is not None:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    return log_file


def build_uvicorn_log_config(log_file: Path) -> dict[str, Any]:
    """Return a pythonw-safe uvicorn logging config (never crashes on None stdout)."""
    handlers: dict[str, Any] = {
        "file": {
            "class": "logging.FileHandler",
            "filename": str(log_file),
            "encoding": "utf-8",
            "formatter": "default",
        }
    }
    handler_names = ["file"]
    if sys.stderr is not None:
        handlers["stderr"] = {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "formatter": "default",
        }
        handler_names.append("stderr")

    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
                "datefmt": "%Y-%m-%dT%H:%M:%S",
            }
        },
        "handlers": handlers,
        "loggers": {
            "uvicorn": {"handlers": handler_names, "level": "INFO", "propagate": False},
            "uvicorn.error": {"handlers": handler_names, "level": "INFO", "propagate": False},
            "uvicorn.access": {"handlers": handler_names, "level": "WARNING", "propagate": False},
        },
    }
