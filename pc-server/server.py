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
from urllib.parse import quote, unquote

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from config import (
    AFTER_DOWNLOAD_DELETE_DELAY_SECONDS,
    APP_NAME,
    APP_VERSION,
    MAX_FILE_SIZE_BYTES,
    OUTBOX_CLEANUP_INTERVAL_SECONDS,
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
    get_outbox_stats,
    guess_mime_type,
    iso_now,
    iter_file_chunks,
    public_item_view,
    safe_delete_outbox_file,
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
    outbox_ttl_minutes: int | None = Field(default=None, ge=0, le=43200)
    auto_delete_after_download: bool | None = None


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
    after_download_delay_seconds: float = AFTER_DOWNLOAD_DELETE_DELAY_SECONDS,
    cleanup_interval_seconds: float = OUTBOX_CLEANUP_INTERVAL_SECONDS,
) -> FastAPI:
    """Build and configure the QuickDrop LAN FastAPI application."""
    history = HistoryStore(settings_manager.data_dir / "history.json")
    hub = EventHub()

    notifier = DesktopNotifier(
        enabled_getter=lambda: enable_notifications and settings_manager.settings.notifications_enabled,
        auto_copy_getter=lambda: settings_manager.settings.auto_copy_clipboard,
        web_url_getter=lambda: f"http://127.0.0.1:{settings_manager.settings.port}",
        icon_path=icon_path,
    )

    mdns_advertiser: MdnsAdvertiser | None = None
    mdns_task: asyncio.Task[bool] | None = None
    cleanup_task: asyncio.Task[None] | None = None
    pending_deletes: dict[str, asyncio.Task[None]] = {}

    def _publish_outbox_stats() -> dict[str, Any]:
        stats = get_outbox_stats(settings_manager.outbox_dir())
        payload = {
            **stats,
            "outbox_ttl_minutes": settings_manager.settings.outbox_ttl_minutes,
            "auto_delete_after_download": settings_manager.settings.auto_delete_after_download,
        }
        hub.publish("outbox_updated", payload)
        return payload

    def _run_ttl_cleanup_sync() -> list[dict[str, Any]]:
        ttl = settings_manager.settings.outbox_ttl_minutes
        if ttl <= 0:
            return []
        return history.cleanup_expired_outbox(settings_manager.outbox_dir(), ttl)

    async def _run_ttl_cleanup_and_notify() -> int:
        updated = await asyncio.to_thread(_run_ttl_cleanup_sync)
        if updated:
            for view in updated:
                hub.publish("item_updated", view)
            _publish_outbox_stats()
            logger.info("Limpieza TTL de outbox: %d copia(s) temporal(es) expirada(s).", len(updated))
        return len(updated)

    def _cancel_pending_delete(item_id: str) -> None:
        task = pending_deletes.pop(item_id, None)
        if task is not None and not task.done():
            task.cancel()

    def _schedule_outbox_delete_after_download(item_id: str) -> None:
        if not settings_manager.settings.auto_delete_after_download:
            return
        item = history.get_item(item_id)
        if (
            not item
            or item.get("kind") != "file"
            or item.get("direction") != "to_phone"
            or not item.get("is_temp_outbox")
            or not item.get("stored_path")
        ):
            return
        if item_id in pending_deletes and not pending_deletes[item_id].done():
            return

        async def _delayed_delete() -> None:
            try:
                await asyncio.sleep(max(0.0, after_download_delay_seconds))
                if not settings_manager.settings.auto_delete_after_download:
                    return
                latest = history.get_item(item_id)
                if (
                    not latest
                    or latest.get("direction") != "to_phone"
                    or not latest.get("is_temp_outbox")
                    or not latest.get("stored_path")
                ):
                    return
                deleted = await asyncio.to_thread(
                    safe_delete_outbox_file,
                    Path(latest["stored_path"]),
                    settings_manager.outbox_dir(),
                )
                if deleted or not Path(latest["stored_path"]).exists():
                    expired = history.mark_expired(item_id)
                    if expired:
                        hub.publish("item_updated", public_item_view(expired))
                    _publish_outbox_stats()
                    logger.info(
                        "Copia temporal eliminada tras descarga completa: %s",
                        latest.get("filename"),
                    )
            except asyncio.CancelledError:
                pass
            finally:
                pending_deletes.pop(item_id, None)

        pending_deletes[item_id] = asyncio.create_task(_delayed_delete())

    async def _outbox_cleanup_loop() -> None:
        try:
            while True:
                await asyncio.sleep(max(5.0, cleanup_interval_seconds))
                try:
                    await _run_ttl_cleanup_and_notify()
                except Exception as exc:
                    logger.warning("Error en limpieza periódica de outbox: %s", exc)
        except asyncio.CancelledError:
            pass

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        nonlocal mdns_advertiser, mdns_task, cleanup_task
        # Ensure separate downloads and outbox directories exist on startup
        settings_manager.download_dir()
        settings_manager.outbox_dir()
        # Run initial TTL sweep on startup and start periodic 5-minute cleaner
        await _run_ttl_cleanup_and_notify()
        cleanup_task = asyncio.create_task(_outbox_cleanup_loop())
        if enable_mdns and settings_manager.settings.mdns_enabled:
            mdns_advertiser = MdnsAdvertiser(
                device_name=settings_manager.settings.resolved_device_name(),
                port=settings_manager.settings.port,
            )
            # Register mDNS in background thread so HTTP/Web UI is ready immediately
            mdns_task = asyncio.create_task(asyncio.to_thread(mdns_advertiser.start))
        logger.info(
            "%s v%s iniciado en http://%s:%d (descargas: %s | outbox: %s)",
            APP_NAME,
            APP_VERSION,
            get_primary_lan_ip(),
            settings_manager.settings.port,
            settings_manager.download_dir(),
            settings_manager.outbox_dir(),
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
            if cleanup_task is not None and not cleanup_task.done():
                cleanup_task.cancel()
            for task in list(pending_deletes.values()):
                if not task.done():
                    task.cancel()
            pending_deletes.clear()
            if mdns_task is not None and not mdns_task.done():
                mdns_task.cancel()
            if mdns_advertiser is not None:
                await asyncio.to_thread(mdns_advertiser.stop)
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

    @app.middleware("http")
    async def no_cache_web_assets(request: Request, call_next):
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"
        return response

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
        stats = await asyncio.to_thread(get_outbox_stats, settings_manager.outbox_dir())
        return {
            "app": APP_NAME,
            "version": APP_VERSION,
            "name": f"QuickDrop-{cfg.resolved_device_name()}",
            "hostname": cfg.resolved_device_name(),
            "ip": lan_ip,
            "port": cfg.port,
            "lan_url": f"http://{lan_ip}:{cfg.port}",
            "download_dir": str(settings_manager.download_dir()),
            "outbox_dir": str(settings_manager.outbox_dir()),
            "max_file_size_bytes": MAX_FILE_SIZE_BYTES,
            "auto_copy_clipboard": cfg.auto_copy_clipboard,
            "notifications_enabled": cfg.notifications_enabled,
            "outbox_ttl_minutes": cfg.outbox_ttl_minutes,
            "auto_delete_after_download": cfg.auto_delete_after_download,
            "outbox_size_bytes": stats["total_bytes"],
            "outbox_file_count": stats["file_count"],
        }

    @app.get("/api/outbox/stats")
    async def outbox_stats() -> dict[str, Any]:
        stats = await asyncio.to_thread(get_outbox_stats, settings_manager.outbox_dir())
        return {
            **stats,
            "outbox_ttl_minutes": settings_manager.settings.outbox_ttl_minutes,
            "auto_delete_after_download": settings_manager.settings.auto_delete_after_download,
        }

    @app.post("/api/outbox/clear")
    async def clear_outbox_endpoint(request: Request) -> dict[str, Any]:
        _ensure_loopback(request)
        for item_id in list(pending_deletes.keys()):
            _cancel_pending_delete(item_id)
        deleted_count, freed_bytes, updated_views = await asyncio.to_thread(
            history.clear_outbox,
            settings_manager.outbox_dir(),
        )
        for view in updated_views:
            hub.publish("item_updated", view)
        stats = _publish_outbox_stats()
        logger.info(
            "Outbox limpiado manualmente: %d archivo(s), %d bytes liberados.",
            deleted_count,
            freed_bytes,
        )
        return {
            "cleared_files": deleted_count,
            "freed_bytes": freed_bytes,
            **stats,
        }

    @app.patch("/api/settings")
    async def update_settings(payload: SettingsUpdatePayload, request: Request) -> dict[str, Any]:
        _ensure_loopback(request)
        updated = settings_manager.update(
            auto_copy_clipboard=payload.auto_copy_clipboard,
            notifications_enabled=payload.notifications_enabled,
            outbox_ttl_minutes=payload.outbox_ttl_minutes,
            auto_delete_after_download=payload.auto_delete_after_download,
        )
        if payload.outbox_ttl_minutes is not None and updated.outbox_ttl_minutes > 0:
            await _run_ttl_cleanup_and_notify()
        settings_payload = {
            "auto_copy_clipboard": updated.auto_copy_clipboard,
            "notifications_enabled": updated.notifications_enabled,
            "outbox_ttl_minutes": updated.outbox_ttl_minutes,
            "auto_delete_after_download": updated.auto_delete_after_download,
        }
        hub.publish("settings_updated", settings_payload)
        return settings_payload

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
        is_temp = direction == "to_phone"
        item = history.add_item(
            direction=direction,
            kind="file",
            filename=final_path.name,
            stored_path=final_path,
            mime_type=guess_mime_type(final_path.name, mime_type),
            size_bytes=size_bytes,
            sha256=sha256,
            sender=sender.strip() or ("Android" if direction == "to_pc" else "PC"),
            is_temp_outbox=is_temp,
        )
        view = public_item_view(item)
        hub.publish("item_created", view)
        if is_temp:
            _publish_outbox_stats()

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
        raw_sender = request.headers.get("x-sender")
        sender = (
            unquote(raw_sender).strip()
            if raw_sender
            else (
                settings_manager.settings.resolved_device_name()
                if direction == "to_phone"
                else "Android"
            )
        )

        dest_dir = (
            settings_manager.outbox_dir()
            if direction == "to_phone"
            else settings_manager.download_dir()
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
            settings_manager.outbox_dir()
            if direction == "to_phone"
            else settings_manager.download_dir()
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
    @app.get("/api/history")
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
        if updated.get("direction") == "to_phone" and updated.get("is_temp_outbox"):
            _schedule_outbox_delete_after_download(item_id)
        return view

    @app.delete("/api/items/{item_id}")
    async def delete_history_item(item_id: str) -> dict[str, Any]:
        removed = history.remove_item(item_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Elemento no encontrado.")
        _cancel_pending_delete(item_id)
        deleted_temp_file = False
        # Strictly delete ONLY temporary outbox copies (to_phone); NEVER touch Downloads\QuickDrop (to_pc)
        if (
            removed.get("kind") == "file"
            and removed.get("direction") == "to_phone"
            and removed.get("is_temp_outbox")
            and removed.get("stored_path")
        ):
            deleted_temp_file = await asyncio.to_thread(
                safe_delete_outbox_file,
                Path(removed["stored_path"]),
                settings_manager.outbox_dir(),
            )
            _publish_outbox_stats()
        hub.publish("item_removed", {"id": item_id})
        return {"deleted": True, "id": item_id, "deleted_temp_file": deleted_temp_file}

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
            settings_manager.download_dir(),
            settings_manager.outbox_dir(),
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

        should_schedule_cleanup = (
            not inline
            and item.get("direction") == "to_phone"
            and bool(item.get("is_temp_outbox"))
        )

        async def _tracked_stream(start_byte: int, end_byte: int, trigger_on_complete: bool) -> AsyncIterator[bytes]:
            completed = False
            try:
                async for chunk in iter_file_chunks(file_path, start=start_byte, end=end_byte):
                    yield chunk
                completed = True
            finally:
                if completed and trigger_on_complete:
                    _schedule_outbox_delete_after_download(item_id)

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
            reaches_eof = end == file_size - 1
            return StreamingResponse(
                _tracked_stream(start, end, should_schedule_cleanup and reaches_eof),
                status_code=206,
                media_type=mime_type,
                headers=headers,
            )

        headers["Content-Length"] = str(file_size)
        return StreamingResponse(
            _tracked_stream(0, file_size - 1, should_schedule_cleanup),
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
                settings_manager.download_dir(),
                settings_manager.outbox_dir(),
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
            settings_manager.download_dir(),
            settings_manager.outbox_dir(),
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
        folder = settings_manager.download_dir()
        if os.name == "nt":
            await asyncio.to_thread(os.startfile, str(folder))
        return JSONResponse({"opened": str(folder)})

    # --- Real-time SSE Stream ---

    @app.get("/api/events")
    async def events_stream(request: Request) -> StreamingResponse:
        queue = hub.subscribe()

        async def _generator() -> AsyncIterator[str]:
            try:
                # Immediate handshake frame so browser EventSource fires onopen right away
                yield "retry: 3000\n\n"
                yield f"event: connected\ndata: {json.dumps({'status': 'ok', 'ts': iso_now()})}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        evt = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"event: {evt['event']}\ndata: {json.dumps(evt['data'], ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        if await request.is_disconnected():
                            break
                        yield ": ping\n\n"
            except asyncio.CancelledError:
                pass
            finally:
                hub.unsubscribe(queue)

        return StreamingResponse(
            _generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # --- Minimalist Web UI (supports PyInstaller sys._MEIPASS) ---

    web_dir = get_resource_dir() / "web"
    if web_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(web_dir)), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            return FileResponse(
                web_dir / "index.html",
                headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
            )
    else:
        logger.error("Carpeta web/ no encontrada en %s", web_dir)

    return app
