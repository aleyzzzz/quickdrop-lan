#!/usr/bin/env python3
"""Control remoto seguro de PC Windows 11 (Rama 1 - Antigravity-Hub).

Subcomandos:
  - estado: muestra CPU, RAM, discos y descargas activas.
  - pausar-media: envía tecla multimedia Play/Pause (VK_MEDIA_PLAY_PAUSE).
  - suspender: suspende la PC (soporta --dry-run).
  - apagar-en <minutos>: programa apagado en N minutos (soporta --dry-run).
  - cancelar-apagado: cancela un apagado programado (soporta --dry-run).
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import socket
import string
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
LOG_PATH = ROOT_DIR / "logs" / "control_pc.log"

sys.path.insert(0, str(ROOT_DIR / "scripts" / "common"))
import notify_telegram  # noqa: E402

IN_PROGRESS_EXTS = {".part", ".!qb", ".tmp", ".crdownload", ".downloading", ".aria2"}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log_line(level: str, message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"{now_iso()} [{level}] {message}\n")


def run_ps_json(ps_script: str, timeout: int = 15) -> tuple[bool, Any, str]:
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return False, None, str(exc)
    out = (res.stdout or "").strip()
    err = (res.stderr or "").strip()
    if not out:
        return res.returncode == 0, None, err
    try:
        return True, json.loads(out), err
    except json.JSONDecodeError:
        return False, None, err or out[:200]


def get_memory_fallback() -> dict[str, Any]:
    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    stat = MEMORYSTATUSEX()
    stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
    total_gb = round(stat.ullTotalPhys / (1024**3), 2)
    free_gb = round(stat.ullAvailPhys / (1024**3), 2)
    used_gb = round(total_gb - free_gb, 2)
    return {"total_gb": total_gb, "used_gb": used_gb, "free_gb": free_gb, "used_pct": stat.dwMemoryLoad}


def get_system_metrics() -> dict[str, Any]:
    ps = (
        "$cpu = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average; "
        "$os = Get-CimInstance Win32_OperatingSystem; "
        "$totGB = [math]::Round($os.TotalVisibleMemorySize / 1MB, 2); "
        "$freeGB = [math]::Round($os.FreePhysicalMemory / 1MB, 2); "
        "$usedGB = [math]::Round($totGB - $freeGB, 2); "
        "$pct = if ($totGB -gt 0) { [math]::Round(($usedGB / $totGB) * 100, 1) } else { 0 }; "
        "$uptimeH = [math]::Round(((Get-Date) - $os.LastBootUpTime).TotalHours, 1); "
        "$procs = @(Get-Process | Where-Object { $_.Name -match 'qbittorrent|jdownloader|jellyfin|stremio|rclone' } | Select-Object -ExpandProperty Name -Unique); "
        "[PSCustomObject]@{cpu_pct=$cpu; ram=@{total_gb=$totGB; used_gb=$usedGB; free_gb=$freeGB; used_pct=$pct}; uptime_hours=$uptimeH; media_procs=$procs} | ConvertTo-Json -Compress"
    )
    ok, data, _ = run_ps_json(ps, timeout=20)
    if ok and isinstance(data, dict):
        procs = data.get("media_procs") or []
        if isinstance(procs, str):
            procs = [procs]
        return {
            "cpu_pct": data.get("cpu_pct"),
            "ram": data.get("ram") or get_memory_fallback(),
            "uptime_hours": data.get("uptime_hours"),
            "media_procs": procs,
        }
    return {
        "cpu_pct": None,
        "ram": get_memory_fallback(),
        "uptime_hours": None,
        "media_procs": [],
    }


def get_disks_summary() -> list[dict[str, Any]]:
    disks: list[dict[str, Any]] = []
    for d in string.ascii_uppercase:
        root = f"{d}:\\"
        if os.path.exists(root):
            try:
                u = shutil.disk_usage(root)
                total_gb = round(u.total / (1024**3), 1)
                free_gb = round(u.free / (1024**3), 1)
                free_pct = round((u.free / u.total) * 100, 1) if u.total else 0.0
                disks.append({"drive": f"{d}:", "free_gb": free_gb, "total_gb": total_gb, "free_pct": free_pct})
            except OSError:
                pass
    return disks


def detect_active_downloads() -> list[str]:
    env = notify_telegram.load_env()
    watch_dirs: list[Path] = []
    dl_env = env.get("DOWNLOADS_DIR", "").strip()
    if dl_env:
        watch_dirs.append(Path(dl_env))
    else:
        watch_dirs.append(Path.home() / "Downloads")
    jd_dir = Path(r"D:\descarga jdownloader")
    if jd_dir.exists() and jd_dir not in watch_dirs:
        watch_dirs.append(jd_dir)

    active: list[str] = []
    for folder in watch_dirs:
        try:
            if not folder.exists():
                continue
            for item in folder.rglob("*"):
                if item.is_file() and item.suffix.lower() in IN_PROGRESS_EXTS:
                    active.append(str(item))
                    if len(active) >= 20:
                        return active
        except OSError:
            continue
    return active


def cmd_estado(args: argparse.Namespace) -> int:
    metrics = get_system_metrics()
    disks = get_disks_summary()
    active_dl = detect_active_downloads()
    payload = {
        "timestamp": now_iso(),
        "hostname": socket.gethostname(),
        "cpu_pct": metrics["cpu_pct"],
        "ram": metrics["ram"],
        "uptime_hours": metrics["uptime_hours"],
        "disks": disks,
        "media_procs": metrics["media_procs"],
        "active_downloads": active_dl,
    }
    log_line(
        "INFO",
        f"cmd=estado cpu={metrics['cpu_pct']}% ram={metrics['ram']['used_pct']}% "
        f"active_dl={len(active_dl)} procs={','.join(metrics['media_procs']) or 'ninguno'}",
    )

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        ram = metrics["ram"]
        cpu_str = f"{metrics['cpu_pct']}%" if metrics["cpu_pct"] is not None else "N/D"
        up_str = f"{metrics['uptime_hours']} h" if metrics["uptime_hours"] is not None else "N/D"
        lines = [
            f"=== ESTADO PC ({payload['hostname']}) ===",
            f"Fecha:      {payload['timestamp']}",
            f"CPU:        {cpu_str}",
            f"RAM:        {ram['used_gb']} / {ram['total_gb']} GB ({ram['used_pct']}% usado)",
            f"Uptime:     {up_str}",
            "Discos:     " + " | ".join(f"{d['drive']} {d['free_gb']}/{d['total_gb']} GB ({d['free_pct']}% libre)" for d in disks),
            "Apps media: " + (", ".join(metrics["media_procs"]) if metrics["media_procs"] else "ninguna activa"),
            f"Descargas activas (.part/.!qB/.tmp): {len(active_dl)}",
        ]
        for path in active_dl[:5]:
            lines.append(f"  - {path}")
        print("\n".join(lines))

    if args.notify:
        ram = metrics["ram"]
        msg = (
            f"*Estado PC ({payload['hostname']})*\n"
            f"CPU: `{metrics['cpu_pct']}%` | RAM: `{ram['used_gb']}/{ram['total_gb']} GB ({ram['used_pct']}%)`\n"
            f"Descargas activas: `{len(active_dl)}` | Apps: `{', '.join(metrics['media_procs']) or 'ninguna'}`"
        )
        notify_telegram.send_telegram(msg)
    return 0


def cmd_pausar_media(args: argparse.Namespace) -> int:
    if args.dry_run:
        msg = "[DRY-RUN] Se enviaría la tecla multimedia Play/Pause (VK_MEDIA_PLAY_PAUSE)."
        log_line("INFO", "cmd=pausar-media dry_run=True")
        print(msg)
        return 0

    VK_MEDIA_PLAY_PAUSE = 0xB3
    KEYEVENTF_KEYUP = 0x0002
    user32 = ctypes.windll.user32
    user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, 0, 0)
    user32.keybd_event(VK_MEDIA_PLAY_PAUSE, 0, KEYEVENTF_KEYUP, 0)
    log_line("INFO", "cmd=pausar-media dry_run=False result=OK")
    print("Tecla Play/Pause enviada correctamente.")
    if args.notify:
        notify_telegram.send_telegram("Reproducción multimedia pausada/reanudada en la PC.")
    return 0


def cmd_suspender(args: argparse.Namespace) -> int:
    if args.dry_run:
        log_line("INFO", "cmd=suspender dry_run=True")
        print("[DRY-RUN] Se suspendería la PC mediante SetSuspendState (modo suspensión, sin hibernar).")
        return 0

    log_line("WARN", "cmd=suspender dry_run=False ejecutando")
    if args.notify:
        notify_telegram.send_telegram("Suspendiendo la PC ahora...")
    res = subprocess.run(
        ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
        capture_output=True,
        text=True,
    )
    return res.returncode


def cmd_apagar_en(args: argparse.Namespace) -> int:
    minutes = int(args.minutos)
    if minutes < 1 or minutes > 1440:
        print("Error: indicá un valor entre 1 y 1440 minutos.", file=sys.stderr)
        return 2
    seconds = minutes * 60
    if args.dry_run:
        log_line("INFO", f"cmd=apagar-en minutos={minutes} dry_run=True")
        print(f"[DRY-RUN] Se programaría apagado en {minutes} min ({seconds} s): shutdown /s /t {seconds}")
        return 0

    res = subprocess.run(
        ["shutdown", "/s", "/t", str(seconds), "/c", f"Apagado programado en {minutes} min (Antigravity-Hub)"],
        capture_output=True,
        text=True,
        encoding="cp850",
        errors="replace",
    )
    ok = res.returncode == 0
    log_line("WARN" if ok else "ERROR", f"cmd=apagar-en minutos={minutes} rc={res.returncode}")
    if ok:
        print(f"Apagado programado en {minutes} minuto(s). Usá 'cancelar-apagado' para anularlo.")
        if args.notify:
            notify_telegram.send_telegram(f"Apagado de la PC programado en *{minutes} min*.")
    else:
        print(f"No se pudo programar el apagado (rc={res.returncode}): {(res.stdout + res.stderr).strip()}", file=sys.stderr)
    return 0 if ok else res.returncode


def cmd_cancelar_apagado(args: argparse.Namespace) -> int:
    if args.dry_run:
        log_line("INFO", "cmd=cancelar-apagado dry_run=True")
        print("[DRY-RUN] Se cancelaría cualquier apagado programado: shutdown /a")
        return 0

    res = subprocess.run(
        ["shutdown", "/a"],
        capture_output=True,
        text=True,
        encoding="cp850",
        errors="replace",
    )
    if res.returncode == 0:
        log_line("INFO", "cmd=cancelar-apagado result=cancelado")
        print("Apagado programado cancelado.")
        if args.notify:
            notify_telegram.send_telegram("Apagado programado de la PC cancelado.")
        return 0
    if res.returncode == 1116:
        log_line("INFO", "cmd=cancelar-apagado result=sin_apagado_pendiente")
        print("No había ningún apagado programado.")
        return 0
    log_line("ERROR", f"cmd=cancelar-apagado rc={res.returncode}")
    print(f"Error al cancelar apagado (rc={res.returncode}): {(res.stdout + res.stderr).strip()}", file=sys.stderr)
    return res.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Control remoto seguro de PC (Rama 1 - Antigravity-Hub).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_est = sub.add_parser("estado", help="Muestra CPU, RAM, discos y descargas activas.")
    p_est.add_argument("--json", action="store_true", help="Salida en formato JSON.")
    p_est.add_argument("--notify", action="store_true", help="Enviar resumen también a Telegram.")
    p_est.set_defaults(func=cmd_estado)

    p_pm = sub.add_parser("pausar-media", help="Pausa o reanuda la reproducción multimedia actual.")
    p_pm.add_argument("--dry-run", action="store_true", help="Simula sin enviar la tecla multimedia.")
    p_pm.add_argument("--notify", action="store_true", help="Avisar por Telegram.")
    p_pm.set_defaults(func=cmd_pausar_media)

    p_sus = sub.add_parser("suspender", help="Suspende la PC de forma segura.")
    p_sus.add_argument("--dry-run", action="store_true", help="Simula sin suspender la PC.")
    p_sus.add_argument("--notify", action="store_true", help="Avisar por Telegram antes de suspender.")
    p_sus.set_defaults(func=cmd_suspender)

    p_ap = sub.add_parser("apagar-en", help="Programa el apagado de la PC en N minutos.")
    p_ap.add_argument("minutos", type=int, help="Minutos hasta el apagado (1-1440).")
    p_ap.add_argument("--dry-run", action="store_true", help="Simula sin programar el apagado.")
    p_ap.add_argument("--notify", action="store_true", help="Avisar por Telegram.")
    p_ap.set_defaults(func=cmd_apagar_en)

    p_ca = sub.add_parser("cancelar-apagado", help="Cancela un apagado programado.")
    p_ca.add_argument("--dry-run", action="store_true", help="Simula sin ejecutar shutdown /a.")
    p_ca.add_argument("--notify", action="store_true", help="Avisar por Telegram.")
    p_ca.set_defaults(func=cmd_cancelar_apagado)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
