"""FastAPI asynchronous streaming server for QuickDrop LAN."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import (
    APP_NAME,
    APP_VERSION,
    MAX_FILE_SIZE_BYTES,
    STREAM_CHUNK_SIZE,
    SettingsManager,
    get_primary_lan_ip,
    get_resource_dir,
)
from mdns import MdnsAdvertiser
from notifier import DesktopNotifier
from storage import (
    FileTooLargeError,
    HistoryStore,
    detect_text_kind,
    guess_mime_type,
    iso_now,
    iter_file_chunks,
    public_item_view,
    save_stream_to_disk,
)

logger = logging.getLogger("quickdrop.server")

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost", "testclient"}


class TextPayload(BaseModel):
    content: str = Field(..., min_length=1, max_length=500_000)
    sender: str = Field(default="Android", max_length=80)
    auto_copy: bool | None = None


class SettingsUpdatePayload(BaseModel):
    auto_copy_clipboard: bool | None = None
    notifications_enabled: bool | None = None


class EventHub:
    """Lightweight bounded Server-Sent Events pub/sub hub."""

    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=64)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self._subscribers.discard(queue)

    def publish(self, event_type: str, data: dict[str, Any]) -> None:
        payload = {"event": event_type, "data": data}
        for queue in list(self._subscribers):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass


def _is_loopback_request(request: Request) -> bool:
    client = request.client
    if client is None:
        return False
    return client.host in _LOOPBACK_HOSTS


def _ensure_loopback(request: Request) -> None:
    if not _is_loopback_request(request):
        raise HTTPException(status_code=403, detail="Acción permitida solo desde esta PC.")


def _validate_path_within(path: Path, allowed_roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
        for root in allowed_roots:
            try:
                resolved.relative_to(root.resolve())
                return True
            except ValueError:
                continue
    except OSError:
        return False
    return False


def create_app(
    settings_manager: SettingsManager,
    *,
    enable_mdns: bool = True,
    enable_notifications: bool = True,
    icon_path: Path | None = None,
) -> FastAPI:
    """Build and configure the QuickDrop LAN FastAPI application."""
    history = HistoryStore(settings_manager.data_dir / "history.json")
    hub = EventHub()
    settings = settings_manager.settings

    notifier = DesktopNotifier(
        enabled_getter=lambda: enable_notifications and settings_manager.settings.notifications_enabled,
        auto_copy_getter=lambda: settings_manager.settings.auto_copy_clipboard,
        web_url_getter=lambda: f"http://127.0.0.1:{settings_manager.settings.port}",
        icon_path=icon_path,
    )

    mdns_advertiser: MdnsAdvertiser | None = None

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        nonlocal mdns_advertiser
        # Ensure directories exist on startup
        settings_manager.settings.resolved_download_dir()
        settings_manager.settings.resolved_outbox_dir()
        if enable_mdns and settings_manager.settings.mdns_enabled:
            mdns_advertiser = MdnsAdvertiser(
                device_name=settings_manager.settings.resolved_device_name(),
                port=settings_manager.settings.port,
            )
            mdns_advertiser.start()
        logger.info(
            "%s v%s iniciado en http://%s:%d (descargas: %s)",
            APP_NAME,
            APP_VERSION,
            get_primary_lan_ip(),
            settings_manager.settings.port,
            settings_manager.settings.resolved_download_dir(),
        )
        if os.name == "nt":
            try:
                import ctypes
                import gc

                gc.collect()
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                ctypes.windll.kernel32.SetProcessWorkingSetSize(handle, -1, -1)
            except Exception:
                pass
        try:
            yield
        finally:
            if mdns_advertiser is not None:
                mdns_advertiser.stop()
                mdns_advertiser = None
            logger.info("%s detenido correctamente.", APP_NAME)

    app = FastAPI(
        title=APP_NAME,
        version=APP_VERSION,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    # Expose internals for tray/tests
    app.state.settings_manager = settings_manager
    app.state.history = history
    app.state.hub = hub
    app.state.notifier = notifier

    # --- Info & Health ---

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "ts": iso_now()}

    @app.get("/api/info")
    async def info() -> dict[str, Any]:
        cfg = settings_manager.settings
        lan_ip = get_primary_lan_ip()
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "name": f"QuickDrop-{cfg.resolved_device_name()}",
            "hostname": cfg.resolved_device_name(),
            "ip": lan_ip,
            "port": cfg.port,
            "lan_url": f"http://{lan_ip}:{cfg.port}",
            "download_dir": str(cfg.resolved_download_dir()),
            "max_file_size_bytes": MAX_FILE_SIZE_BYTES,
            "auto_copy_clipboard": cfg.auto_copy_clipboard,
            "notifications_enabled": cfg.notifications_enabled,
        }

    @app.patch("/api/settings")
    async def update_settings(payload: SettingsUpdatePayload, request: Request) -> dict[str, Any]:
        _ensure_loopback(request)
        updated = settings_manager.update(
            auto_copy_clipboard=payload.auto_copy_clipboard,
            notifications_enabled=payload.notifications_enabled,
        )
        hub.publish(
            "settings_updated",
            {
                "auto_copy_clipboard": updated.auto_copy_clipboard,
                "notifications_enabled": updated.notifications_enabled,
            },
        )
        return {
            "auto_copy_clipboard": updated.auto_copy_clipboard,
            "notifications_enabled": updated.notifications_enabled,
        }

    # --- Helpers for Text & File Transfers ---

    async def _handle_text(payload: TextPayload, *, direction: str) -> dict[str, Any]:
        text = payload.content.strip()
        if not text:
            raise HTTPException(status_code=400, detail="El contenido no puede estar vacío.")

        kind = detect_text_kind(text)
        mime = "text/uri-list" if kind == "link" else "text/plain"
        item = history.add_item(
            direction=direction,
            kind=kind,
            content=text,
            mime_type=mime,
            size_bytes=len(text.encode("utf-8")),
            sender=payload.sender.strip() or ("Android" if direction == "to_pc" else "PC"),
        )
        view = public_item_view(item)
        hub.publish("item_created", view)

        if direction == "to_pc":
            should_copy = (
                payload.auto_copy
                if payload.auto_copy is not None
                else settings_manager.settings.auto_copy_clipboard
            )
            copied = await asyncio.to_thread(notifier.copy_to_clipboard, text, should_copy) if should_copy else False
            await asyncio.to_thread(
                notifier.notify_link_or_text,
                kind=kind,
                content=text,
                sender=item["sender"],
                copied=copied,
            )
            view["copied_to_clipboard"] = copied

        logger.info("Recibido %s (%s, %d B) desde %s", kind, direction, item["size_bytes"], item["sender"])
        return view

    async def _finalize_file_upload(
        *,
        final_path: Path,
        size_bytes: int,
        sha256: str,
        mime_type: str,
        sender: str,
        direction: str,
    ) -> dict[str, Any]:
        item = history.add_item(
            direction=direction,
            kind="file",
            filename=final_path.name,
            stored_path=final_path,
            mime_type=guess_mime_type(final_path.name, mime_type),
            size_bytes=size_bytes,
            sha256=sha256,
            sender=sender.strip() or ("Android" if direction == "to_pc" else "PC"),
        )
        view = public_item_view(item)
        hub.publish("item_created", view)

        if direction == "to_pc":
            await asyncio.to_thread(
                notifier.notify_file_received,
                file_path=final_path,
                size_bytes=size_bytes,
                sender=item["sender"],
            )

        logger.info(
            "Archivo guardado (%s): %s (%d bytes, sha256=%s...)",
            direction,
            final_path.name,
            size_bytes,
            sha256[:12],
        )
        return view

    async def _handle_raw_upload(request: Request, *, default_direction: str) -> dict[str, Any]:
        content_length_hdr = request.headers.get("content-length")
        if content_length_hdr:
            try:
                declared_size = int(content_length_hdr)
                if declared_size > MAX_FILE_SIZE_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="El archivo excede el límite máximo de 2 GB.",
                    )
            except ValueError:
                pass

        direction = request.headers.get("x-direction", default_direction).strip().lower()
        if direction not in ("to_pc", "to_phone"):
            direction = default_direction

        raw_filename = request.headers.get("x-filename") or request.query_params.get("filename")
        mime_type = request.headers.get("x-mime-type") or request.headers.get("content-type")
        sender = request.headers.get("x-sender") or ("PC" if direction == "to_phone" else "Android")

        dest_dir = (
            settings_manager.settings.resolved_outbox_dir()
            if direction == "to_phone"
            else settings_manager.settings.resolved_download_dir()
        )

        try:
            final_path, total_bytes, sha256 = await save_stream_to_disk(
                request.stream(),
                destination_dir=dest_dir,
                raw_filename=raw_filename,
                max_bytes=MAX_FILE_SIZE_BYTES,
            )
        except FileTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc

        if total_bytes == 0:
            try:
                final_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise HTTPException(status_code=400, detail="El archivo está vacío (0 bytes).")

        return await _finalize_file_upload(
            final_path=final_path,
            size_bytes=total_bytes,
            sha256=sha256,
            mime_type=mime_type or "",
            sender=sender,
            direction=direction,
        )

    async def _handle_multipart_upload(
        *,
        file: UploadFile,
        sender: str,
        direction: str,
    ) -> dict[str, Any]:
        dest_dir = (
            settings_manager.settings.resolved_outbox_dir()
            if direction == "to_phone"
            else settings_manager.settings.resolved_download_dir()
        )

        async def _chunks() -> AsyncIterator[bytes]:
            while True:
                chunk = await file.read(STREAM_CHUNK_SIZE)
                if not chunk:
                    break
                yield chunk

        try:
            final_path, total_bytes, sha256 = await save_stream_to_disk(
                _chunks(),
                destination_dir=dest_dir,
                raw_filename=file.filename,
                max_bytes=MAX_FILE_SIZE_BYTES,
            )
        except FileTooLargeError as exc:
            raise HTTPException(status_code=413, detail=str(exc)) from exc
        finally:
            await file.close()

        if total_bytes == 0:
            try:
                final_path.unlink(missing_ok=True)
            except OSError:
                pass
            raise HTTPException(status_code=400, detail="El archivo está vacío (0 bytes).")

        return await _finalize_file_upload(
            final_path=final_path,
            size_bytes=total_bytes,
            sha256=sha256,
            mime_type=file.content_type or "",
            sender=sender,
            direction=direction,
        )

    # --- Phone -> PC Endpoints ---

    @app.post("/api/text")
    async def receive_text(payload: TextPayload) -> dict[str, Any]:
        return await _handle_text(payload, direction="to_pc")

    @app.post("/api/upload/raw")
    async def upload_raw(request: Request) -> dict[str, Any]:
        return await _handle_raw_upload(request, default_direction="to_pc")

    @app.post("/api/upload")
    async def upload_multipart(
        file: UploadFile = File(...),
        sender: str = Form(default="Android"),
        direction: str = Form(default="to_pc"),
    ) -> dict[str, Any]:
        norm_dir = direction if direction in ("to_pc", "to_phone") else "to_pc"
        return await _handle_multipart_upload(file=file, sender=sender, direction=norm_dir)

    # --- PC -> Phone Endpoints ---

    @app.post("/api/pc-send/text")
    async def pc_send_text(payload: TextPayload) -> dict[str, Any]:
        if not payload.sender or payload.sender == "Android":
            payload.sender = settings_manager.settings.resolved_device_name()
        return await _handle_text(payload, direction="to_phone")

    @app.post("/api/pc-send/upload/raw")
    async def pc_send_raw(request: Request) -> dict[str, Any]:
        return await _handle_raw_upload(request, default_direction="to_phone")

    @app.post("/api/pc-send/upload")
    async def pc_send_multipart(
        file: UploadFile = File(...),
        sender: str = Form(default=""),
    ) -> dict[str, Any]:
        resolved_sender = sender.strip() or settings_manager.settings.resolved_device_name()
        return await _handle_multipart_upload(file=file, sender=resolved_sender, direction="to_phone")

    # --- History & File Streaming Download ---

    @app.get("/api/items")
    async def list_items(
        direction: str | None = Query(default=None),
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        items = [public_item_view(i) for i in history.list_items(direction=direction, limit=limit)]
        return {"items": items, "count": len(items)}

    @app.post("/api/items/{item_id}/ack")
    async def ack_item(item_id: str) -> dict[str, Any]:
        updated = history.mark_downloaded(item_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Elemento no encontrado.")
        view = public_item_view(updated)
        hub.publish("item_updated", view)
        return view

    @app.delete("/api/items/{item_id}")
    async def delete_history_item(item_id: str) -> dict[str, Any]:
        removed = history.remove_item(item_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Elemento no encontrado.")
        hub.publish("item_removed", {"id": item_id})
        return {"deleted": True, "id": item_id}

    @app.get("/api/files/{item_id}")
    async def download_file(
        item_id: str,
        request: Request,
        inline: bool = Query(default=False),
    ) -> StreamingResponse:
        item = history.get_item(item_id)
        if not item or item.get("kind") != "file" or not item.get("stored_path"):
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")

        file_path = Path(item["stored_path"])
        allowed_roots = [
            settings_manager.settings.resolved_download_dir(),
            settings_manager.settings.resolved_outbox_dir(),
        ]
        if not _validate_path_within(file_path, allowed_roots) or not file_path.is_file():
            raise HTTPException(status_code=404, detail="El archivo ya no existe en disco.")

        file_size = file_path.stat().st_size
        mime_type = item.get("mime_type") or "application/octet-stream"
        filename = item.get("filename") or file_path.name
        disposition_type = "inline" if inline else "attachment"
        encoded_name = quote(filename, safe="")
        ascii_fallback = filename.encode("ascii", "ignore").decode("ascii").replace('"', "_") or "file"

        headers = {
            "Accept-Ranges": "bytes",
            "Content-Disposition": (
                f'{disposition_type}; filename="{ascii_fallback}"; '
                f"filename*=UTF-8''{encoded_name}"
            ),
        }

        range_header = request.headers.get("range")
        if range_header:
            match = _RANGE_RE.match(range_header.strip())
            if not match:
                raise HTTPException(status_code=416, detail="Rango inválido.")
            start_str, end_str = match.groups()
            if start_str == "" and end_str == "":
                raise HTTPException(status_code=416, detail="Rango vacío.")
            if start_str == "":
                suffix_len = int(end_str)
                start = max(0, file_size - suffix_len)
                end = file_size - 1
            else:
                start = int(start_str)
                end = int(end_str) if end_str else file_size - 1

            if start >= file_size or end < start:
                raise HTTPException(
                    status_code=416,
                    detail="Rango fuera de límites.",
                    headers={"Content-Range": f"bytes */{file_size}"},
                )
            end = min(end, file_size - 1)
            content_len = end - start + 1
            headers["Content-Range"] = f"bytes {start}-{end}/{file_size}"
            headers["Content-Length"] = str(content_len)
            return StreamingResponse(
                iter_file_chunks(file_path, start=start, end=end),
                status_code=206,
                media_type=mime_type,
                headers=headers,
            )

        headers["Content-Length"] = str(file_size)
        return StreamingResponse(
            iter_file_chunks(file_path, start=0, end=file_size - 1),
            status_code=200,
            media_type=mime_type,
            headers=headers,
        )

    # --- Local PC Convenience Actions (strictly loopback-only) ---

    @app.post("/api/items/{item_id}/open")
    async def open_item_locally(item_id: str, request: Request) -> JSONResponse:
        _ensure_loopback(request)
        item = history.get_item(item_id)
        if not item:
            raise HTTPException(status_code=404, detail="Elemento no encontrado.")

        if item["kind"] == "link" and item.get("content"):
            url = item["content"].strip()
            if not url.lower().startswith(("http://", "https://")):
                raise HTTPException(status_code=400, detail="Esquema de URL no permitido.")
            await asyncio.to_thread(webbrowser.open, url)
            return JSONResponse({"opened": True})

        if item["kind"] == "file" and item.get("stored_path"):
            file_path = Path(item["stored_path"])
            allowed_roots = [
                settings_manager.settings.resolved_download_dir(),
                settings_manager.settings.resolved_outbox_dir(),
            ]
            if not _validate_path_within(file_path, allowed_roots) or not file_path.exists():
                raise HTTPException(status_code=404, detail="Archivo no encontrado en disco.")
            if os.name == "nt":
                await asyncio.to_thread(os.startfile, str(file_path))
            return JSONResponse({"opened": True})

        raise HTTPException(status_code=400, detail="Este elemento no se puede abrir.")

    @app.post("/api/items/{item_id}/reveal")
    async def reveal_item_in_explorer(item_id: str, request: Request) -> JSONResponse:
        _ensure_loopback(request)
        item = history.get_item(item_id)
        if not item or not item.get("stored_path"):
            raise HTTPException(status_code=404, detail="Archivo no encontrado.")

        file_path = Path(item["stored_path"])
        allowed_roots = [
            settings_manager.settings.resolved_download_dir(),
            settings_manager.settings.resolved_outbox_dir(),
        ]
        if not _validate_path_within(file_path, allowed_roots) or not file_path.exists():
            raise HTTPException(status_code=404, detail="Archivo no encontrado en disco.")

        if os.name == "nt":
            await asyncio.to_thread(
                subprocess.Popen,
                ["explorer.exe", f"/select,{file_path}"],
            )
        return JSONResponse({"revealed": True})

    @app.post("/api/open-downloads")
    async def open_downloads_folder(request: Request) -> JSONResponse:
        _ensure_loopback(request)
        folder = settings_manager.settings.resolved_download_dir()
        if os.name == "nt":
            await asyncio.to_thread(os.startfile, str(folder))
        return JSONResponse({"opened": str(folder)})

    # --- Real-time SSE Stream ---

    @app.get("/api/events")
    async def events_stream(request: Request) -> StreamingResponse:
        queue = hub.subscribe()

        async def _generator() -> AsyncIterator[str]:
            try:
                yield f"event: connected\ndata: {json.dumps({'ts': iso_now()})}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        evt = await asyncio.wait_for(queue.get(), timeout=20.0)
                        yield f"event: {evt['event']}\ndata: {json.dumps(evt['data'], ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                hub.unsubscribe(queue)

        return StreamingResponse(
            _generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # --- Minimalist Web UI ---

    web_dir = get_resource_dir() / "web"
    if web_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(web_dir / "index.html")

    return app
