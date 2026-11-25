"""Automated end-to-end verification for QuickDrop LAN PC server.

Starts the real uvicorn server in a subprocess (headless, isolated temp dirs),
sends links, text, raw streaming binary files, multipart uploads, and tests
chunked downloads + history persistence + memory footprint / leak check.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PC_SERVER_DIR = Path(__file__).resolve().parent.parent
TEST_PORT = 18765
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"


def _get_child_pids(parent_pid: int) -> list[int]:
    """Return all descendant PIDs on Windows using Toolhelp32Snapshot (stdlib ctypes)."""
    if os.name != "nt":
        return []
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(wintypes.ULONG)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    snap = ctypes.windll.kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snap == wintypes.HANDLE(-1).value:
        return []
    parent_map: dict[int, list[int]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(entry)
        if ctypes.windll.kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            while True:
                parent_map.setdefault(entry.th32ParentProcessID, []).append(entry.th32ProcessID)
                if not ctypes.windll.kernel32.Process32NextW(snap, ctypes.byref(entry)):
                    break
    finally:
        ctypes.windll.kernel32.CloseHandle(snap)

    descendants: list[int] = []
    stack = [parent_pid]
    while stack:
        cur = stack.pop()
        for child in parent_map.get(cur, []):
            descendants.append(child)
            stack.append(child)
    return descendants


def get_process_rss_mb(pid: int) -> tuple[float, float]:
    """Return (working_set_mb, private_mb) for the actual server process (or child of venv stub)."""
    if os.name != "nt":
        return -1.0, -1.0
    import ctypes
    from ctypes import wintypes

    class PROCESS_MEMORY_COUNTERS_EX(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
            ("PrivateUsage", ctypes.c_size_t),
        ]

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    PROCESS_VM_READ = 0x0010

    def _read_single(target_pid: int) -> tuple[float, float]:
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_VM_READ, False, target_pid
        )
        if not handle:
            return 0.0, 0.0
        try:
            counters = PROCESS_MEMORY_COUNTERS_EX()
            counters.cb = ctypes.sizeof(counters)
            ok = ctypes.windll.psapi.GetProcessMemoryInfo(
                handle, ctypes.byref(counters), counters.cb
            )
            if ok:
                return (
                    counters.WorkingSetSize / (1024 * 1024),
                    counters.PrivateUsage / (1024 * 1024),
                )
        finally:
            ctypes.windll.kernel32.CloseHandle(handle)
        return 0.0, 0.0

    # On Windows, venv\Scripts\python.exe is a tiny stub spawning the real interpreter.
    children = _get_child_pids(pid)
    target = children[0] if children else pid
    return _read_single(target)


def http_json(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def wait_for_health(timeout_sec: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_sec
    last_err = None
    while time.monotonic() < deadline:
        try:
            status, payload = http_json("GET", "/api/health")
            if status == 200 and payload.get("status") == "ok":
                return
        except Exception as exc:
            last_err = exc
            time.sleep(0.15)
    raise RuntimeError(f"El servidor no respondio a /api/health: {last_err}")


def stream_upload_raw(filename: str, size_bytes: int, chunk_size: int = 1024 * 1024) -> tuple[dict, str]:
    """Stream synthetic deterministic binary data via raw HTTP request without holding it all in RAM."""
    import http.client

    hasher = hashlib.sha256()
    conn = http.client.HTTPConnection("127.0.0.1", TEST_PORT, timeout=60)
    try:
        conn.putrequest("POST", "/api/upload/raw")
        conn.putheader("X-Filename", urllib.parse.quote(filename))
        conn.putheader("X-Mime-Type", "application/octet-stream")
        conn.putheader("X-Sender", "TestPhone")
        conn.putheader("Content-Length", str(size_bytes))
        conn.endheaders()

        remaining = size_bytes
        pattern_block = (b"QUICKDROP-STREAM-VERIFY-" * 43691)[:chunk_size]
        seq = 0
        while remaining > 0:
            to_send = min(chunk_size, remaining)
            # Vary first 8 bytes per chunk so SHA-256 validates order too
            prefix = seq.to_bytes(8, "big")
            chunk = prefix + pattern_block[8:to_send] if to_send >= 8 else prefix[:to_send]
            hasher.update(chunk)
            conn.send(chunk)
            remaining -= to_send
            seq += 1

        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        if resp.status != 200:
            raise AssertionError(f"Upload raw fallo ({resp.status}): {body}")
        return json.loads(body), hasher.hexdigest()
    finally:
        conn.close()


def upload_multipart_file(filename: str, content: bytes) -> dict:
    boundary = "----QuickDropTestBoundary98765"
    parts = [
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="sender"\r\n\r\nTestCurl\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: image/gif\r\n\r\n"
    ]
    payload = parts[0].encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    req = urllib.request.Request(
        f"{BASE_URL}/api/upload",
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        assert resp.status == 200
        return json.loads(resp.read().decode("utf-8"))


def run_tests() -> int:
    with tempfile.TemporaryDirectory(prefix="quickdrop_test_") as tmp_dir:
        tmp_path = Path(tmp_dir)
        download_dir = tmp_path / "downloads"
        data_dir = tmp_path / "data"

        cmd = [
            sys.executable,
            str(PC_SERVER_DIR / "tray_app.py"),
            "--headless",
            "--no-notifications",
            "--no-mdns",
            "--host",
            "127.0.0.1",
            "--port",
            str(TEST_PORT),
            "--download-dir",
            str(download_dir),
            "--data-dir",
            str(data_dir),
        ]

        proc = subprocess.Popen(
            cmd,
            cwd=str(PC_SERVER_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            wait_for_health()
            rss_idle, priv_idle = get_process_rss_mb(proc.pid)
            print(
                f"[PASS] Servidor levantado. RAM en reposo: "
                f"WorkingSet={rss_idle:.2f} MiB, Private={priv_idle:.2f} MiB"
            )

            # 1. Verify /api/info and Web UI index
            status, info = http_json("GET", "/api/info")
            assert status == 200 and info["port"] == TEST_PORT
            with urllib.request.urlopen(f"{BASE_URL}/", timeout=5) as resp:
                html = resp.read().decode("utf-8")
                assert resp.status == 200 and "QuickDrop LAN" in html
            print("[PASS] /api/info y Web UI (/) responden correctamente.")

            # 2. Send a Link (Phone -> PC)
            test_link = "https://github.com/fastapi/fastapi"
            status, link_item = http_json(
                "POST",
                "/api/text",
                {"content": test_link, "sender": "Pixel-Test", "auto_copy": False},
            )
            assert status == 200
            assert link_item["kind"] == "link"
            assert link_item["direction"] == "to_pc"
            assert link_item["content"] == test_link
            print(f"[PASS] Link enviado y clasificado: {link_item['id']}")

            # 3. Send Plain Text (PC -> Phone)
            status, pc_text = http_json(
                "POST",
                "/api/pc-send/text",
                {"content": "Nota de prueba hacia Android", "sender": "Win11-PC"},
            )
            assert status == 200
            assert pc_text["kind"] == "text"
            assert pc_text["direction"] == "to_phone"
            print(f"[PASS] Texto PC -> Android registrado: {pc_text['id']}")

            # 4. Multipart upload (simulating GIF / curl -F)
            gif_bytes = b"GIF89a" + os.urandom(128 * 1024)
            gif_sha = hashlib.sha256(gif_bytes).hexdigest()
            mp_item = upload_multipart_file("animacion prueba.gif", gif_bytes)
            assert mp_item["kind"] == "file"
            assert mp_item["sha256"] == gif_sha
            saved_gif = Path(mp_item["stored_path"])
            assert saved_gif.is_file() and saved_gif.stat().st_size == len(gif_bytes)
            print(f"[PASS] Upload multipart verificado ({saved_gif.name}, SHA-256 ok).")

            # 5. Raw streaming uploads (3 x 32 MiB = 96 MiB total) to verify streaming & no memory leaks
            rss_samples = []
            for idx in range(3):
                size_mb = 32
                size_bytes = size_mb * 1024 * 1024
                item, expected_sha = stream_upload_raw(f"video_grande_{idx}.bin", size_bytes)
                assert item["size_bytes"] == size_bytes
                assert item["sha256"] == expected_sha
                saved_path = Path(item["stored_path"])
                assert saved_path.is_file() and saved_path.stat().st_size == size_bytes
                # Verify chunked download with Range header
                req = urllib.request.Request(
                    f"{BASE_URL}/api/files/{item['id']}",
                    headers={"Range": "bytes=0-1023"},
                )
                with urllib.request.urlopen(req, timeout=10) as r:
                    assert r.status == 206
                    partial = r.read()
                    assert len(partial) == 1024
                rss_now, priv_now = get_process_rss_mb(proc.pid)
                rss_samples.append(priv_now)
                print(
                    f"[PASS] Stream raw #{idx + 1} ({size_mb} MiB) guardado y verificado. "
                    f"RAM actual: WorkingSet={rss_now:.2f} MiB, Private={priv_now:.2f} MiB"
                )

            # 6. Oversize Content-Length (> 2 GiB) rejected with 413 immediately
            import http.client

            conn = http.client.HTTPConnection("127.0.0.1", TEST_PORT, timeout=10)
            try:
                conn.putrequest("POST", "/api/upload/raw")
                conn.putheader("X-Filename", "huge.iso")
                conn.putheader("Content-Length", str(2 * 1024 * 1024 * 1024 + 1024))
                conn.endheaders()
                resp = conn.getresponse()
                assert resp.status == 413, f"Esperado 413, recibido {resp.status}"
            finally:
                conn.close()
            print("[PASS] Rechazo HTTP 413 para archivos > 2 GiB verificado.")

            # 7. Verify history JSON persisted cleanly on disk
            history_file = data_dir / "history.json"
            assert history_file.is_file()
            persisted = json.loads(history_file.read_text(encoding="utf-8"))
            assert len(persisted) == 6  # link + text + gif + 3 raw binaries
            assert persisted[-1]["content"] == test_link
            status, api_items = http_json("GET", "/api/items")
            assert status == 200 and api_items["count"] == 6
            print(f"[PASS] Historial JSON verificado en disco ({len(persisted)} registros).")

            # 8. Check memory stability (after streaming 96 MiB, RAM delta must stay tiny, no leak)
            priv_delta = rss_samples[-1] - rss_samples[0]
            print(
                f"[INFO] Resumen RAM (Private): idle={priv_idle:.2f} MiB, "
                f"tras 32 MiB={rss_samples[0]:.2f} MiB, "
                f"tras 96 MiB={rss_samples[-1]:.2f} MiB (delta={priv_delta:+.2f} MiB)"
            )
            assert abs(priv_delta) < 15.0, f"Posible fuga de memoria detectada: delta={priv_delta:.2f} MiB"
            print("[PASS] Sin fugas de memoria tras 96 MiB en streaming.")
            return 0
        finally:
            for child_pid in _get_child_pids(proc.pid):
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(child_pid), "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        check=False,
                    )
                except OSError:
                    pass
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(run_tests())
