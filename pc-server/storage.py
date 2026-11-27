"""Streaming file storage, strict outbox cleanup cage, and atomic JSON history store."""

from __future__ import annotations

import asyncio
import hashlib
import json
import mimetypes
import os
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator
from urllib.parse import unquote

from config import MAX_FILE_SIZE_BYTES, MAX_HISTORY_ITEMS, STREAM_CHUNK_SIZE

_URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)
_INVALID_WIN_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


class FileTooLargeError(ValueError):
    """Raised when an uploaded stream exceeds MAX_FILE_SIZE_BYTES."""


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def detect_text_kind(content: str) -> str:
    stripped = content.strip()
    if _URL_RE.match(stripped):
        return "link"
    return "text"


def sanitize_filename(raw_name: str | None) -> str:
    """Sanitize untrusted filename for Windows/POSIX filesystems without path traversal."""
    if not raw_name:
        return f"archivo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"

    decoded = unquote(raw_name).strip()
    # Keep only the final path component regardless of Windows or Unix separators
    decoded = decoded.replace("\\", "/").split("/")[-1]
    cleaned = _INVALID_WIN_CHARS_RE.sub("_", decoded).strip(" .")
    if not cleaned:
        cleaned = f"archivo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.bin"

    stem = Path(cleaned).stem.upper()
    if stem in _WINDOWS_RESERVED_NAMES:
        cleaned = f"_{cleaned}"

    # Limit filename length to keep paths well under Windows MAX_PATH
    if len(cleaned) > 180:
        suffix = Path(cleaned).suffix[:24]
        base = Path(cleaned).stem[: 180 - len(suffix)]
        cleaned = f"{base}{suffix}"

    return cleaned


def allocate_unique_path(directory: Path, filename: str) -> Path:
    """Pick a non-colliding file path inside directory (never overwrites user files)."""
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while True:
        alt = directory / f"{stem} ({counter}){suffix}"
        if not alt.exists():
            return alt
        counter += 1


def guess_mime_type(filename: str, provided: str | None = None) -> str:
    if provided and provided.strip() and provided.strip().lower() != "application/octet-stream":
        return provided.strip()
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def is_strictly_inside_outbox(file_path: Path, outbox_dir: Path) -> bool:
    """Strict safety cage: returns True ONLY if resolved file_path is strictly inside outbox_dir."""
    try:
        resolved_outbox = outbox_dir.resolve()
        resolved_file = file_path.resolve()
        return resolved_file != resolved_outbox and resolved_file.is_relative_to(resolved_outbox)
    except OSError:
        return False


def safe_delete_outbox_file(file_path: Path, outbox_dir: Path) -> bool:
    """Delete a temporary outbox file ONLY if it resides strictly inside outbox_dir.

    Never touches files inside Downloads\\QuickDrop or anywhere outside outbox_dir.
    """
    if not is_strictly_inside_outbox(file_path, outbox_dir):
        return False
    try:
        if file_path.is_file() or file_path.is_symlink():
            file_path.unlink(missing_ok=True)
            return True
    except OSError:
        return False
    return False


def get_outbox_stats(outbox_dir: Path) -> dict[str, int]:
    """Return total bytes and file count currently stored inside outbox_dir."""
    total_bytes = 0
    file_count = 0
    if not outbox_dir.is_dir():
        return {"total_bytes": 0, "file_count": 0}
    try:
        for entry in outbox_dir.iterdir():
            if entry.name.endswith(".part") or not entry.is_file():
                continue
            if not is_strictly_inside_outbox(entry, outbox_dir):
                continue
            try:
                total_bytes += entry.stat().st_size
                file_count += 1
            except OSError:
                continue
    except OSError:
        pass
    return {"total_bytes": total_bytes, "file_count": file_count}


async def save_stream_to_disk(
    stream: AsyncIterator[bytes],
    destination_dir: Path,
    raw_filename: str | None,
    max_bytes: int = MAX_FILE_SIZE_BYTES,
) -> tuple[Path, int, str]:
    """Stream chunks directly to disk via a temp .part file and atomic replace.

    Returns (final_path, total_bytes, sha256_hex).
    Peak memory overhead is ~STREAM_CHUNK_SIZE regardless of total file size.
    """
    destination_dir.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(raw_filename)
    tmp_path = destination_dir / f".quickdrop_{uuid.uuid4().hex}.part"

    hasher = hashlib.sha256()
    total_bytes = 0
    file_handle = open(tmp_path, "wb")
    try:
        async for chunk in stream:
            if not chunk:
                continue
            total_bytes += len(chunk)
            if total_bytes > max_bytes:
                raise FileTooLargeError(
                    f"El archivo excede el límite máximo de {max_bytes // (1024 * 1024)} MB."
                )
            hasher.update(chunk)
            await asyncio.to_thread(file_handle.write, chunk)
        await asyncio.to_thread(file_handle.flush)
    except BaseException:
        file_handle.close()
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    else:
        file_handle.close()

    final_path = allocate_unique_path(destination_dir, safe_name)
    os.replace(tmp_path, final_path)
    return final_path, total_bytes, hasher.hexdigest()


async def iter_file_chunks(
    path: Path,
    start: int = 0,
    end: int | None = None,
    chunk_size: int = STREAM_CHUNK_SIZE,
) -> AsyncIterator[bytes]:
    """Yield a file range in fixed-size chunks without loading it into RAM."""
    file_size = path.stat().st_size
    last_byte = file_size - 1 if end is None else min(end, file_size - 1)
    remaining = max(0, last_byte - start + 1)

    f = open(path, "rb")
    try:
        if start > 0:
            await asyncio.to_thread(f.seek, start)
        while remaining > 0:
            to_read = min(chunk_size, remaining)
            data = await asyncio.to_thread(f.read, to_read)
            if not data:
                break
            remaining -= len(data)
            yield data
    finally:
        f.close()


class HistoryStore:
    """Thread-safe, bounded JSON history store with atomic writes and safe outbox cleanup."""

    def __init__(self, history_path: Path, max_items: int = MAX_HISTORY_ITEMS) -> None:
        self.history_path = history_path
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        self.max_items = max_items
        self._lock = threading.RLock()
        self._items: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        try:
            data = json.loads(self.history_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[: self.max_items]
        except (OSError, json.JSONDecodeError):
            pass
        return []

    def _persist(self) -> None:
        tmp = self.history_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(self._items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, self.history_path)

    def add_item(
        self,
        *,
        direction: str,
        kind: str,
        content: str | None = None,
        filename: str | None = None,
        stored_path: Path | None = None,
        mime_type: str = "text/plain",
        size_bytes: int = 0,
        sha256: str | None = None,
        sender: str = "Unknown",
        is_temp_outbox: bool = False,
    ) -> dict[str, Any]:
        item: dict[str, Any] = {
            "id": uuid.uuid4().hex,
            "direction": direction,
            "kind": kind,
            "content": content,
            "filename": filename,
            "stored_path": str(stored_path) if stored_path else None,
            "mime_type": mime_type,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "sender": sender,
            "created_at": iso_now(),
            "downloaded_by_phone": False,
            "is_temp_outbox": bool(is_temp_outbox),
            "file_expired": False,
        }
        with self._lock:
            self._items.insert(0, item)
            if len(self._items) > self.max_items:
                self._items = self._items[: self.max_items]
            self._persist()
        return dict(item)

    def list_items(
        self,
        direction: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        with self._lock:
            items = self._items
            if direction in ("to_pc", "to_phone"):
                items = [i for i in items if i.get("direction") == direction]
            return [dict(i) for i in items[: max(1, min(limit, self.max_items))]]

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._items:
                if item.get("id") == item_id:
                    return dict(item)
        return None

    def mark_downloaded(self, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._items:
                if item.get("id") == item_id:
                    item["downloaded_by_phone"] = True
                    self._persist()
                    return dict(item)
        return None

    def mark_expired(self, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            for item in self._items:
                if item.get("id") == item_id:
                    item["file_expired"] = True
                    self._persist()
                    return dict(item)
        return None

    def remove_item(self, item_id: str) -> dict[str, Any] | None:
        """Remove an entry from history JSON and return the removed record (or None)."""
        with self._lock:
            for idx, item in enumerate(self._items):
                if item.get("id") == item_id:
                    removed = self._items.pop(idx)
                    self._persist()
                    return dict(removed)
        return None

    def cleanup_expired_outbox(
        self,
        outbox_dir: Path,
        ttl_minutes: int,
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Delete temporary outbox files older than ttl_minutes and mark history entries expired."""
        if ttl_minutes <= 0:
            return []

        ref_now = now if now is not None else datetime.now().astimezone()
        cutoff = ref_now - timedelta(minutes=ttl_minutes)
        cutoff_ts = cutoff.timestamp()
        updated_views: list[dict[str, Any]] = []
        changed = False

        with self._lock:
            for item in self._items:
                if (
                    item.get("kind") != "file"
                    or item.get("direction") != "to_phone"
                    or not item.get("is_temp_outbox")
                ):
                    continue
                stored = item.get("stored_path")
                if not stored:
                    continue

                created_dt = _parse_iso_datetime(item.get("created_at"))
                file_path = Path(stored)
                is_old = False
                if created_dt is not None:
                    is_old = created_dt.timestamp() <= cutoff_ts
                elif is_strictly_inside_outbox(file_path, outbox_dir) and file_path.is_file():
                    try:
                        is_old = file_path.stat().st_mtime <= cutoff_ts
                    except OSError:
                        is_old = False

                if not is_old:
                    continue

                deleted = safe_delete_outbox_file(file_path, outbox_dir)
                if deleted or (not item.get("file_expired") and not file_path.exists()):
                    item["file_expired"] = True
                    changed = True
                    updated_views.append(public_item_view(item))

            if changed:
                self._persist()

        # Also clean orphaned expired files strictly inside outbox_dir (skipping active .part)
        if outbox_dir.is_dir():
            try:
                for entry in list(outbox_dir.iterdir()):
                    if entry.name.endswith(".part") or not entry.is_file():
                        continue
                    if not is_strictly_inside_outbox(entry, outbox_dir):
                        continue
                    try:
                        if entry.stat().st_mtime <= cutoff_ts:
                            safe_delete_outbox_file(entry, outbox_dir)
                    except OSError:
                        continue
            except OSError:
                pass

        return updated_views

    def clear_outbox(self, outbox_dir: Path) -> tuple[int, int, list[dict[str, Any]]]:
        """Delete all temporary files strictly inside outbox_dir and mark matching history entries expired."""
        deleted_count = 0
        freed_bytes = 0

        if outbox_dir.is_dir():
            try:
                for entry in list(outbox_dir.iterdir()):
                    if entry.name.endswith(".part") or not entry.is_file():
                        continue
                    if not is_strictly_inside_outbox(entry, outbox_dir):
                        continue
                    try:
                        size = entry.stat().st_size
                    except OSError:
                        size = 0
                    if safe_delete_outbox_file(entry, outbox_dir):
                        deleted_count += 1
                        freed_bytes += size
            except OSError:
                pass

        updated_views: list[dict[str, Any]] = []
        changed = False
        with self._lock:
            for item in self._items:
                if (
                    item.get("kind") == "file"
                    and item.get("direction") == "to_phone"
                    and item.get("is_temp_outbox")
                    and not item.get("file_expired")
                ):
                    stored = item.get("stored_path")
                    if stored:
                        safe_delete_outbox_file(Path(stored), outbox_dir)
                    item["file_expired"] = True
                    changed = True
                    updated_views.append(public_item_view(item))
            if changed:
                self._persist()

        return deleted_count, freed_bytes, updated_views


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.astimezone()
        return dt
    except ValueError:
        return None


def public_item_view(item: dict[str, Any]) -> dict[str, Any]:
    """Return API-safe item representation with accurate file_exists and outbox flags."""
    view = dict(item)
    view["is_temp_outbox"] = bool(view.get("is_temp_outbox", False))
    view["file_expired"] = bool(view.get("file_expired", False))
    if view.get("kind") == "file" and view.get("stored_path"):
        view["download_url"] = f"/api/files/{view['id']}"
        try:
            view["file_exists"] = Path(view["stored_path"]).is_file()
        except OSError:
            view["file_exists"] = False
    else:
        view["download_url"] = None
        view["file_exists"] = False
    return view
