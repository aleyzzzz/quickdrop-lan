"""Windows native toast notifications and clipboard helpers for QuickDrop LAN."""

from __future__ import annotations

import html
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Callable

from config import APP_NAME

logger = logging.getLogger("quickdrop.notifier")

_SAFE_HTTP_URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _escape_ps_xml_text(value: str) -> str:
    """Make text safe for winotify's PowerShell here-string and XML CDATA."""
    safe = value.replace("]]>", "] ]>").replace('"', "'")
    return safe.replace("`", "``").replace("$", "`$")


def _escape_ps_xml_attr(value: str) -> str:
    """Make URLs/URIs safe for XML attributes inside winotify's PowerShell template."""
    safe = value.replace("$", "%24").replace("`", "%60")
    return html.escape(safe, quote=True)


def format_size(size_bytes: int) -> str:
    if size_bytes < 1024:
        return f"{size_bytes} B"
    for unit in ("KB", "MB", "GB"):
        size_bytes /= 1024.0
        if size_bytes < 1024.0 or unit == "GB":
            return f"{size_bytes:.1f} {unit}"
    return f"{size_bytes:.1f} GB"


class DesktopNotifier:
    """Sends native Windows toast notifications (winotify) and handles clipboard copy."""

    def __init__(
        self,
        *,
        enabled_getter: Callable[[], bool],
        auto_copy_getter: Callable[[], bool],
        web_url_getter: Callable[[], str],
        icon_path: Path | None = None,
    ) -> None:
        self._enabled_getter = enabled_getter
        self._auto_copy_getter = auto_copy_getter
        self._web_url_getter = web_url_getter
        self._icon_path = icon_path

    def copy_to_clipboard(self, text: str, force: bool = False) -> bool:
        if not force and not self._auto_copy_getter():
            return False
        try:
            import pyperclip

            pyperclip.copy(text)
            return True
        except Exception as exc:
            logger.warning("No se pudo copiar al portapapeles: %s", exc)
            return False

    def notify_link_or_text(
        self,
        *,
        kind: str,
        content: str,
        sender: str,
        copied: bool,
    ) -> None:
        if not self._enabled_getter():
            return

        preview = content.strip().replace("\r\n", " ").replace("\n", " ")
        if len(preview) > 140:
            preview = preview[:137] + "..."

        if kind == "link":
            title = f"Enlace recibido de {sender}"
            suffix = " (copiado al portapapeles)" if copied else ""
            msg = f"{preview}{suffix}"
            safe_url = content.strip() if _SAFE_HTTP_URL_RE.match(content.strip()) else None
            actions = [("Abrir enlace", safe_url)] if safe_url else []
            self._show_toast(title=title, msg=msg, launch=safe_url, actions=actions)
        else:
            title = f"Texto recibido de {sender}"
            msg = f"{preview}\nCopiado al portapapeles." if copied else preview
            web_url = self._web_url_getter()
            self._show_toast(
                title=title,
                msg=msg,
                launch=web_url,
                actions=[("Ver en QuickDrop", web_url)],
            )

    def notify_file_received(
        self,
        *,
        file_path: Path,
        size_bytes: int,
        sender: str,
    ) -> None:
        if not self._enabled_getter():
            return

        title = f"Archivo recibido de {sender}"
        msg = f"{file_path.name} ({format_size(size_bytes)})"
        folder_uri = file_path.parent.resolve().as_uri()
        file_uri = file_path.resolve().as_uri()
        self._show_toast(
            title=title,
            msg=msg,
            launch=file_uri,
            actions=[
                ("Abrir archivo", file_uri),
                ("Abrir carpeta", folder_uri),
            ],
        )

    def _show_toast(
        self,
        *,
        title: str,
        msg: str,
        launch: str | None = None,
        actions: list[tuple[str, str]] | None = None,
    ) -> None:
        if os.name != "nt":
            logger.info("Toast omitido (no es Windows): %s - %s", title, msg)
            return
        try:
            from winotify import Notification, audio

            icon_str = str(self._icon_path) if self._icon_path and self._icon_path.exists() else ""
            toast = Notification(
                app_id=APP_NAME,
                title=_escape_ps_xml_text(title),
                msg=_escape_ps_xml_text(msg),
                duration="short",
                icon=icon_str,
            )
            toast.tag = f"qd-{uuid.uuid4().hex[:12]}"
            if launch:
                toast.launch = _escape_ps_xml_attr(launch)
            toast.set_audio(audio.Default, loop=False)
            for label, target in actions or []:
                if target:
                    toast.add_actions(
                        label=_escape_ps_xml_attr(label),
                        launch=_escape_ps_xml_attr(target),
                    )
            toast.show()
        except Exception as exc:
            logger.warning("Error mostrando notificación de Windows: %s", exc)
