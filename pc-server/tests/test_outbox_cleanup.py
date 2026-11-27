"""Automated tests for QuickDrop LAN outbox isolation and safe auto-cleanup."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

PC_SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PC_SERVER_DIR))

from config import SettingsManager
from server import create_app
from storage import HistoryStore, get_outbox_stats, is_strictly_inside_outbox, safe_delete_outbox_file


def test_strict_outbox_cage() -> None:
    with tempfile.TemporaryDirectory(prefix="qd_cage_") as tmp:
        root = Path(tmp)
        downloads = root / "Downloads" / "QuickDrop"
        outbox = root / "AppData" / "outbox"
        downloads.mkdir(parents=True)
        outbox.mkdir(parents=True)

        user_file = downloads / "foto_importante.jpg"
        user_file.write_bytes(b"precious-user-data")
        temp_file = outbox / "copia_temp.bin"
        temp_file.write_bytes(b"temporary-copy")
        traversal_path = outbox / ".." / ".." / "Downloads" / "QuickDrop" / "foto_importante.jpg"

        assert is_strictly_inside_outbox(temp_file, outbox) is True
        assert is_strictly_inside_outbox(outbox, outbox) is False
        assert is_strictly_inside_outbox(user_file, outbox) is False
        assert is_strictly_inside_outbox(traversal_path, outbox) is False

        # Refuses to delete files outside outbox (including traversal attempts)
        assert safe_delete_outbox_file(user_file, outbox) is False
        assert safe_delete_outbox_file(traversal_path, outbox) is False
        assert user_file.is_file()

        # Deletes file strictly inside outbox
        assert safe_delete_outbox_file(temp_file, outbox) is True
        assert not temp_file.exists()
    print("[PASS] 1/6 Jaula estricta de borrado (is_relative_to) verificada.")


def test_ttl_and_clear_unit() -> None:
    with tempfile.TemporaryDirectory(prefix="qd_ttl_") as tmp:
        root = Path(tmp)
        downloads = root / "downloads"
        outbox = root / "data" / "outbox"
        downloads.mkdir(parents=True)
        outbox.mkdir(parents=True)

        history = HistoryStore(root / "data" / "history.json")

        # 1. File received on PC (Downloads) — MUST NEVER be touched by outbox cleanup
        pc_file = downloads / "recibido_de_android.pdf"
        pc_file.write_bytes(b"%PDF-1.4 user document")
        pc_item = history.add_item(
            direction="to_pc",
            kind="file",
            filename=pc_file.name,
            stored_path=pc_file,
            mime_type="application/pdf",
            size_bytes=pc_file.stat().st_size,
            sender="Android",
            is_temp_outbox=False,
        )

        # 2. Expired file in outbox (90 minutes old)
        old_temp = outbox / "video_viejo.mp4"
        old_temp.write_bytes(b"0" * 4096)
        old_item = history.add_item(
            direction="to_phone",
            kind="file",
            filename=old_temp.name,
            stored_path=old_temp,
            mime_type="video/mp4",
            size_bytes=4096,
            sender="PC",
            is_temp_outbox=True,
        )
        # Backdate created_at by 90 minutes
        old_ts = (datetime.now().astimezone() - timedelta(minutes=90)).isoformat(timespec="seconds")
        with history._lock:
            for it in history._items:
                if it["id"] == old_item["id"]:
                    it["created_at"] = old_ts
            history._persist()

        # 3. Fresh file in outbox (just created)
        fresh_temp = outbox / "archivo_reciente.zip"
        fresh_temp.write_bytes(b"1" * 2048)
        fresh_item = history.add_item(
            direction="to_phone",
            kind="file",
            filename=fresh_temp.name,
            stored_path=fresh_temp,
            mime_type="application/zip",
            size_bytes=2048,
            sender="PC",
            is_temp_outbox=True,
        )

        # Run TTL cleanup with 60-minute TTL
        expired = history.cleanup_expired_outbox(outbox, ttl_minutes=60)
        assert len(expired) == 1 and expired[0]["id"] == old_item["id"]
        assert expired[0]["file_expired"] is True and expired[0]["file_exists"] is False
        assert not old_temp.exists()
        assert fresh_temp.is_file()
        assert pc_file.is_file()

        # Manual clear_outbox empties remaining fresh_temp while preserving pc_file
        deleted_count, freed_bytes, cleared_views = history.clear_outbox(outbox)
        assert deleted_count == 1 and freed_bytes == 2048
        assert len(cleared_views) == 1 and cleared_views[0]["id"] == fresh_item["id"]
        assert not fresh_temp.exists()
        assert pc_file.is_file()
        assert get_outbox_stats(outbox) == {"total_bytes": 0, "file_count": 0}
        assert history.get_item(pc_item["id"]) is not None
    print("[PASS] 2/6 Limpieza por TTL y vaciado manual de outbox verificados (Downloads intacto).")


async def test_api_end_to_end() -> None:
    """Exercise real FastAPI routes using an in-process uvicorn server on a local test port."""
    import uvicorn

    test_port = 18769
    base = f"http://127.0.0.1:{test_port}"

    with tempfile.TemporaryDirectory(prefix="qd_api_outbox_") as tmp:
        root = Path(tmp)
        downloads = root / "downloads"
        data_dir = root / "appdata"

        settings_manager = SettingsManager(
            data_dir=data_dir,
            overrides={"host": "127.0.0.1", "port": test_port, "download_dir": str(downloads)},
        )
        app = create_app(
            settings_manager,
            enable_mdns=False,
            enable_notifications=False,
            after_download_delay_seconds=0.35,
            cleanup_interval_seconds=3600.0,
        )

        config = uvicorn.Config(app=app, host="127.0.0.1", port=test_port, log_level="error", access_log=False)
        server = uvicorn.Server(config)
        server_task = asyncio.create_task(server.serve())

        try:
            # Wait until server is ready
            for _ in range(50):
                if server.started:
                    break
                await asyncio.sleep(0.05)
            assert server.started, "El servidor ASGI de pruebas no arranco"

            import urllib.request

            def req_json(method: str, path: str, body: bytes | None = None, headers: dict | None = None) -> dict:
                r = urllib.request.Request(base + path, data=body, headers=headers or {}, method=method)
                with urllib.request.urlopen(r, timeout=10) as resp:
                    assert resp.status == 200
                    return json.loads(resp.read().decode("utf-8"))

            outbox_dir = settings_manager.outbox_dir()
            assert outbox_dir == data_dir / "outbox"

            # 3. Upload PC -> Phone file: must live in outbox (NOT downloads) with is_temp_outbox=True
            payload_pc = b"PC-TO-PHONE-TEMP-DATA-" * 500
            item_outbox_1 = await asyncio.to_thread(
                req_json,
                "POST",
                "/api/pc-send/upload/raw",
                payload_pc,
                {
                    "X-Filename": urllib.parse.quote("paquete_grande.zip"),
                    "X-Mime-Type": "application/zip",
                    "X-Sender": "WinPC",
                    "X-Direction": "to_phone",
                },
            )
            path_outbox_1 = Path(item_outbox_1["stored_path"])
            assert item_outbox_1["is_temp_outbox"] is True
            assert is_strictly_inside_outbox(path_outbox_1, outbox_dir)
            assert not path_outbox_1.resolve().is_relative_to(downloads.resolve())
            assert path_outbox_1.is_file()

            # Upload Phone -> PC file: must live in downloads (NOT outbox) with is_temp_outbox=False
            payload_phone = b"PHONE-TO-PC-REAL-DOWNLOAD-" * 300
            item_dl = await asyncio.to_thread(
                req_json,
                "POST",
                "/api/upload/raw",
                payload_phone,
                {
                    "X-Filename": urllib.parse.quote("foto_celular.jpg"),
                    "X-Mime-Type": "image/jpeg",
                    "X-Sender": "Android",
                    "X-Direction": "to_pc",
                },
            )
            path_dl = Path(item_dl["stored_path"])
            assert item_dl["is_temp_outbox"] is False
            assert path_dl.resolve().is_relative_to(downloads.resolve())
            assert not is_strictly_inside_outbox(path_dl, outbox_dir)
            assert path_dl.is_file()
            print("[PASS] 3/6 Separacion de directorios (to_phone -> outbox, to_pc -> Downloads) verificada.")

            # 4. Preview (?inline=1) must NOT trigger auto-delete; real download (inline=False) + /ack MUST delete
            def fetch_bytes(path: str) -> bytes:
                with urllib.request.urlopen(base + path, timeout=10) as resp:
                    assert resp.status == 200
                    return resp.read()

            preview_data = await asyncio.to_thread(fetch_bytes, f"/api/files/{item_outbox_1['id']}?inline=1")
            assert preview_data == payload_pc
            await asyncio.sleep(0.55)
            assert path_outbox_1.is_file(), "Vista previa (?inline=1) NO debe borrar el archivo temporal"

            downloaded_data = await asyncio.to_thread(fetch_bytes, f"/api/files/{item_outbox_1['id']}")
            assert downloaded_data == payload_pc
            await asyncio.to_thread(req_json, "POST", f"/api/items/{item_outbox_1['id']}/ack", b"{}", {"Content-Type": "application/json"})
            await asyncio.sleep(0.6)
            assert not path_outbox_1.exists(), "La copia en outbox debio auto-borrarse tras descarga completa"
            hist_after_dl = await asyncio.to_thread(req_json, "GET", "/api/history")
            matched = next(i for i in hist_after_dl["items"] if i["id"] == item_outbox_1["id"])
            assert matched["file_expired"] is True and matched["file_exists"] is False
            print("[PASS] 4/6 Preview (?inline=1) conserva archivo; descarga real + /ack auto-borra copia en outbox.")

            # 5. DELETE /api/items/{id}: deletes physical file for to_phone, preserves file for to_pc
            item_outbox_2 = await asyncio.to_thread(
                req_json,
                "POST",
                "/api/pc-send/upload/raw",
                b"TEMP-TO-DELETE" * 200,
                {
                    "X-Filename": "eliminar_directo.bin",
                    "X-Mime-Type": "application/octet-stream",
                    "X-Direction": "to_phone",
                },
            )
            path_outbox_2 = Path(item_outbox_2["stored_path"])
            assert path_outbox_2.is_file()

            del_outbox = await asyncio.to_thread(req_json, "DELETE", f"/api/items/{item_outbox_2['id']}")
            assert del_outbox["deleted"] is True and del_outbox["deleted_temp_file"] is True
            assert not path_outbox_2.exists()

            del_dl = await asyncio.to_thread(req_json, "DELETE", f"/api/items/{item_dl['id']}")
            assert del_dl["deleted"] is True and del_dl["deleted_temp_file"] is False
            assert path_dl.is_file(), "DELETE en item to_pc JAMAS debe borrar el archivo en Downloads"
            print("[PASS] 5/6 DELETE /api/items/{id} borra copia en outbox pero preserva Downloads.")

            # 6. POST /api/outbox/clear + moved Downloads file yields file_exists=False cleanly
            item_outbox_3 = await asyncio.to_thread(
                req_json,
                "POST",
                "/api/pc-send/upload/raw",
                b"CLEAR-ME" * 400,
                {"X-Filename": "temp_clear.bin", "X-Direction": "to_phone"},
            )
            path_outbox_3 = Path(item_outbox_3["stored_path"])
            assert path_outbox_3.is_file()

            item_moved = await asyncio.to_thread(
                req_json,
                "POST",
                "/api/upload/raw",
                b"USER-MOVED-FILE",
                {"X-Filename": "movido.txt", "X-Direction": "to_pc"},
            )
            path_moved = Path(item_moved["stored_path"])
            assert path_moved.is_file()

            # Clear outbox via API
            clear_res = await asyncio.to_thread(req_json, "POST", "/api/outbox/clear")
            assert clear_res["cleared_files"] == 1 and clear_res["total_bytes"] == 0
            assert not path_outbox_3.exists()
            assert path_moved.is_file(), "POST /api/outbox/clear no debe tocar archivos en Downloads"

            # Simulate user manually moving file out of Downloads\QuickDrop
            path_moved.unlink()
            hist = await asyncio.to_thread(req_json, "GET", "/api/history")
            moved_view = next(i for i in hist["items"] if i["id"] == item_moved["id"])
            assert moved_view["file_exists"] is False and moved_view["file_expired"] is False
            print("[PASS] 6/6 POST /api/outbox/clear y estado file_exists=False para archivos movidos verificados.")
        finally:
            server.should_exit = True
            await server_task


def main() -> int:
    test_strict_outbox_cage()
    test_ttl_and_clear_unit()
    asyncio.run(test_api_end_to_end())
    print("[ALL PASS] Todas las pruebas de limpieza automatica y seguridad de outbox pasaron.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
