#!/usr/bin/env python3
"""Chequeo silencioso de salud de PC en Windows 11 (Rama 5 - Antigravity-Hub).

Revisa:
1. Espacio libre y salud de discos (volúmenes y discos físicos).
2. Programas nuevos configurados al inicio de Windows (Registro Run/RunOnce + carpetas Startup).
3. Errores críticos de Windows en Event Viewer (System y Application) de los últimos N días.

Solo lectura: no borra archivos ni modifica Registro, firewall ni configuración de red.
Modo silencioso: registra en logs/salud_pc.log y solo avisa por Telegram si detecta problemas nuevos.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import string
import subprocess
import sys
import winreg
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT_DIR / "state" / "salud_pc.json"
LOG_PATH = ROOT_DIR / "logs" / "salud_pc.log"

sys.path.insert(0, str(ROOT_DIR / "scripts" / "common"))
import notify_telegram  # noqa: E402


def now_dt() -> datetime:
    return datetime.now().astimezone()


def now_iso() -> str:
    return now_dt().isoformat(timespec="seconds")


def log_line(level: str, message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"{now_iso()} [{level}] {message}\n")


def run_ps_json(ps_script: str, timeout: int = 25) -> tuple[bool, Any, str]:
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script]
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:
        return False, None, str(exc)

    stdout = (res.stdout or "").strip()
    stderr = (res.stderr or "").strip()
    if res.returncode != 0 and not stdout:
        return False, None, stderr or f"PowerShell exited with {res.returncode}"
    if not stdout:
        return True, [], stderr
    try:
        return True, json.loads(stdout), stderr
    except json.JSONDecodeError as exc:
        return False, None, f"JSON inválido desde PowerShell: {exc} | {stdout[:200]}"


def ensure_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def check_disks(min_free_pct: float, min_free_gb: float) -> dict[str, Any]:
    volumes: list[dict[str, Any]] = []
    physical: list[dict[str, Any]] = []
    issues: list[str] = []
    warnings: list[str] = []

    ps_vol = (
        "$ErrorActionPreference='Stop'; "
        "@(Get-Volume | Where-Object { $_.DriveLetter -and $_.DriveType -eq 'Fixed' } | "
        "Select-Object DriveLetter, FileSystemLabel, FileSystem, HealthStatus, "
        "@{N='TotalGB';E={[math]::Round($_.Size/1GB,2)}}, "
        "@{N='FreeGB';E={[math]::Round($_.SizeRemaining/1GB,2)}}) | ConvertTo-Json -Compress"
    )
    ok_v, data_v, err_v = run_ps_json(ps_vol)
    if ok_v:
        for item in ensure_list(data_v):
            letter = str(item.get("DriveLetter", "")).strip()
            total_gb = float(item.get("TotalGB") or 0)
            free_gb = float(item.get("FreeGB") or 0)
            free_pct = round((free_gb / total_gb) * 100, 1) if total_gb > 0 else 0.0
            health = str(item.get("HealthStatus") or "Unknown")
            vol = {
                "drive": f"{letter}:",
                "label": str(item.get("FileSystemLabel") or "").strip(),
                "fs": str(item.get("FileSystem") or ""),
                "health": health,
                "total_gb": total_gb,
                "free_gb": free_gb,
                "free_pct": free_pct,
            }
            volumes.append(vol)
            if health.lower() != "healthy":
                issues.append(f"Volumen {vol['drive']} con estado anormal: {health}")
            if total_gb > 0 and (free_pct < min_free_pct or free_gb < min_free_gb):
                issues.append(
                    f"Poco espacio en {vol['drive']} ({vol['free_gb']} GB libres / {vol['free_pct']}% de {vol['total_gb']} GB)"
                )
    else:
        warnings.append(f"No se pudo consultar Get-Volume (usando fallback shutil): {err_v.splitlines()[0]}")
        for d in string.ascii_uppercase:
            root = f"{d}:\\"
            if os.path.exists(root):
                try:
                    usage = shutil.disk_usage(root)
                    total_gb = round(usage.total / (1024**3), 2)
                    free_gb = round(usage.free / (1024**3), 2)
                    free_pct = round((usage.free / usage.total) * 100, 1) if usage.total else 0.0
                    vol = {
                        "drive": f"{d}:",
                        "label": "",
                        "fs": "",
                        "health": "Unknown(fallback)",
                        "total_gb": total_gb,
                        "free_gb": free_gb,
                        "free_pct": free_pct,
                    }
                    volumes.append(vol)
                    if free_pct < min_free_pct or free_gb < min_free_gb:
                        issues.append(
                            f"Poco espacio en {vol['drive']} ({free_gb} GB libres / {free_pct}% de {total_gb} GB)"
                        )
                except OSError:
                    pass

    ps_phys = (
        "$ErrorActionPreference='Stop'; "
        "@(Get-PhysicalDisk | Select-Object FriendlyName, MediaType, BusType, HealthStatus, OperationalStatus, "
        "@{N='SizeGB';E={[math]::Round($_.Size/1GB,2)}}) | ConvertTo-Json -Compress"
    )
    ok_p, data_p, err_p = run_ps_json(ps_phys)
    if ok_p:
        for item in ensure_list(data_p):
            health = str(item.get("HealthStatus") or "Unknown")
            op = item.get("OperationalStatus")
            op_str = ", ".join(op) if isinstance(op, list) else str(op or "Unknown")
            disk = {
                "name": str(item.get("FriendlyName") or "Disco").strip(),
                "media": str(item.get("MediaType") or ""),
                "bus": str(item.get("BusType") or ""),
                "health": health,
                "operational": op_str,
                "size_gb": float(item.get("SizeGB") or 0),
            }
            physical.append(disk)
            if health.lower() != "healthy" or "ok" not in op_str.lower():
                issues.append(f"Salud física degradada en {disk['name']}: Health={health}, Estado={op_str}")
    else:
        warnings.append(f"No se pudo consultar Get-PhysicalDisk: {err_p.splitlines()[0]}")

    volumes.sort(key=lambda v: v["drive"])
    return {
        "volumes": volumes,
        "physical": physical,
        "issues": issues,
        "warnings": warnings,
    }


def collect_startup_items() -> dict[str, dict[str, str]]:
    """Lee programas al inicio (solo lectura) desde Registro Run/RunOnce y carpetas Startup."""
    items: dict[str, dict[str, str]] = {}

    reg_locations = [
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKCU\\Run"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKCU\\RunOnce"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run", "HKLM\\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\RunOnce", "HKLM\\RunOnce"),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Run", "HKLM32\\Run"),
    ]

    for hive, subkey, label in reg_locations:
        try:
            with winreg.OpenKey(hive, subkey, 0, winreg.KEY_READ) as key:
                idx = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(key, idx)
                        idx += 1
                        item_id = f"{label}::{name}"
                        items[item_id] = {
                            "name": str(name),
                            "source": label,
                            "command": str(val),
                        }
                    except OSError:
                        break
        except OSError:
            continue

    startup_dirs = [
        ("StartupUser", Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs\Startup"),
        ("StartupCommon", Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs\Startup"),
    ]
    for label, folder in startup_dirs:
        try:
            if not folder.exists():
                continue
            for entry in sorted(folder.iterdir()):
                if entry.name.lower() == "desktop.ini":
                    continue
                item_id = f"{label}::{entry.name}"
                items[item_id] = {
                    "name": entry.name,
                    "source": label,
                    "command": str(entry),
                }
        except OSError:
            continue

    return items


def check_critical_events(days: int) -> dict[str, Any]:
    """Consulta eventos críticos (Level=1) y fallos graves de disco/BSOD de los últimos N días."""
    ps_events = (
        f"$since = (Get-Date).AddDays(-{int(days)}); "
        "$events = @(); "
        "try { "
        "  $events += Get-WinEvent -FilterHashtable @{LogName=@('System','Application'); Level=1; StartTime=$since} -ErrorAction Stop "
        "} catch {}; "
        "try { "
        "  $events += Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-WER-SystemErrorReporting'; Id=1001; StartTime=$since} -ErrorAction Stop "
        "} catch {}; "
        "try { "
        "  $events += Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName=@('disk','Ntfs'); Id=@(7,55); StartTime=$since} -ErrorAction Stop "
        "} catch {}; "
        "$unique = $events | Sort-Object TimeCreated -Descending | Group-Object { $_.LogName + ':' + $_.RecordId } | ForEach-Object { $_.Group[0] } | Select-Object -First 25; "
        "@($unique | Select-Object "
        "@{N='key';E={$_.LogName + ':' + $_.RecordId}}, "
        "@{N='time';E={$_.TimeCreated.ToString('o')}}, "
        "@{N='log';E={$_.LogName}}, "
        "@{N='id';E={$_.Id}}, "
        "@{N='level';E={$_.LevelDisplayName}}, "
        "@{N='provider';E={$_.ProviderName}}, "
        "@{N='message';E={if ($_.Message) { ($_.Message -replace '\\r?\\n',' ').Substring(0,[Math]::Min(180, ($_.Message -replace '\\r?\\n',' ').Length)) } else { '' }}}) "
        "| ConvertTo-Json -Compress"
    )
    ok, data, err = run_ps_json(ps_events, timeout=30)
    if not ok:
        return {"events": [], "warnings": [f"No se pudieron leer eventos de Windows: {err.splitlines()[0]}"]}
    return {"events": ensure_list(data), "warnings": []}


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "baseline_initialized": False,
        "known_startup": {},
        "seen_critical_events": [],
        "last_disk_fingerprint": "",
        "last_disk_alert_at": "",
        "last_run": "",
    }


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def format_console_report(
    disks: dict[str, Any],
    startup_total: int,
    new_startup: list[dict[str, str]],
    baseline_created: bool,
    new_events: list[dict[str, Any]],
    total_events: int,
    days: int,
    issues: list[str],
    dry_run: bool = False,
) -> str:
    lines = [
        f"=== SALUD DE PC ({socket.gethostname()}) ===",
        f"Fecha: {now_iso()}",
        "",
        "--- 1. Discos (volúmenes) ---",
    ]
    for v in disks["volumes"]:
        lbl = f" [{v['label']}]" if v["label"] else ""
        lines.append(
            f"  {v['drive']}{lbl} — {v['free_gb']} GB libres / {v['total_gb']} GB ({v['free_pct']}% libre) | Salud: {v['health']}"
        )
    if disks["physical"]:
        lines.append("--- Discos físicos ---")
        for p in disks["physical"]:
            lines.append(
                f"  {p['name']} ({p['media']}, {p['size_gb']} GB): Health={p['health']}, Estado={p['operational']}"
            )
    if disks["warnings"]:
        lines.append("  Avisos discos: " + " | ".join(disks["warnings"]))

    lines.append("")
    lines.append(f"--- 2. Programas al inicio ({startup_total} detectados) ---")
    if baseline_created:
        if dry_run:
            lines.append("  Línea base pendiente (modo --dry-run, no se escribió state/salud_pc.json).")
        else:
            lines.append("  Línea base creada en state/salud_pc.json (sin alertas por programas preexistentes).")
    elif new_startup:
        for item in new_startup:
            lines.append(f"  [NUEVO] {item['name']} ({item['source']}): {item['command']}")
    else:
        lines.append("  Sin programas nuevos al inicio.")

    lines.append("")
    lines.append(f"--- 3. Errores críticos de Windows (últimos {days} días) ---")
    if new_events:
        for ev in new_events[:10]:
            lines.append(
                f"  [{ev['time'][:19]}] {ev['log']} ID={ev['id']} ({ev['provider']}): {ev['message']}"
            )
    elif total_events > 0:
        lines.append(f"  {total_events} evento(s) en la ventana ya reportados anteriormente (sin novedades).")
    else:
        lines.append("  Sin errores críticos registrados.")

    lines.append("")
    if issues:
        lines.append(f"ESTADO: ANOMALÍAS DETECTADAS ({len(issues)})")
        for idx, iss in enumerate(issues, 1):
            lines.append(f"  {idx}. {iss}")
    else:
        lines.append("ESTADO: OK (Todo normal - modo silencioso, sin alerta a Telegram)")
    return "\n".join(lines)


def build_telegram_alert(
    disks: dict[str, Any],
    new_startup: list[dict[str, str]],
    new_events: list[dict[str, Any]],
    disk_issues: list[str],
) -> str:
    host = socket.gethostname()
    parts = [f"*Alerta Salud PC — {host}*"]
    if disk_issues:
        parts.append("\n*Discos:*")
        for item in disk_issues:
            parts.append(f"- {item}")
    if new_startup:
        parts.append(f"\n*Programas nuevos al inicio ({len(new_startup)}):*")
        for item in new_startup[:8]:
            parts.append(f"- `{item['name']}` ({item['source']})")
    if new_events:
        parts.append(f"\n*Errores críticos de Windows ({len(new_events)} nuevos):*")
        for ev in new_events[:5]:
            snippet = ev["message"][:100]
            parts.append(f"- `{ev['time'][:16]}` {ev['provider']} (ID {ev['id']}): {snippet}")
    if len(parts) == 1:
        vols = ", ".join(f"{v['drive']} {v['free_gb']}GB ({v['free_pct']}%)" for v in disks["volumes"])
        parts.append(f"Todo normal. Discos: {vols}")
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditoría silenciosa de salud de PC (Rama 5).")
    parser.add_argument("--days", type=int, default=7, help="Días hacia atrás para errores críticos (default: 7).")
    parser.add_argument("--min-free-pct", type=float, default=10.0, help="Umbral mínimo de espacio libre en % (default: 10).")
    parser.add_argument("--min-free-gb", type=float, default=15.0, help="Umbral mínimo de espacio libre en GB (default: 15).")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin actualizar state/ ni enviar alertas a Telegram.")
    parser.add_argument("--force-notify", action="store_true", help="Enviar resumen por Telegram aunque esté todo normal.")
    parser.add_argument("--json", action="store_true", help="Salida en formato JSON.")
    args = parser.parse_args()

    state = load_state()
    disks = check_disks(min_free_pct=args.min_free_pct, min_free_gb=args.min_free_gb)
    current_startup = collect_startup_items()
    ev_res = check_critical_events(days=args.days)

    was_initialized = bool(state.get("baseline_initialized", False))
    known_startup: dict[str, Any] = state.get("known_startup", {})
    new_startup: list[dict[str, str]] = []
    if was_initialized:
        for item_id, meta in sorted(current_startup.items()):
            prev = known_startup.get(item_id)
            if prev is None or prev.get("command") != meta.get("command"):
                new_startup.append(meta)

    seen_events = set(state.get("seen_critical_events", []))
    new_events = [ev for ev in ev_res["events"] if ev.get("key") not in seen_events]

    # Deduplicar alertas de disco si el problema es idéntico y se avisó hace menos de 6 días
    disk_issues = list(disks["issues"])
    disk_fp = hashlib.sha256("|".join(sorted(disk_issues)).encode("utf-8")).hexdigest()[:16] if disk_issues else ""
    disk_should_alert = bool(disk_issues)
    if disk_issues and disk_fp == state.get("last_disk_fingerprint"):
        last_at_str = state.get("last_disk_alert_at", "")
        if last_at_str:
            try:
                last_at = datetime.fromisoformat(last_at_str)
                if now_dt() - last_at < timedelta(days=6):
                    disk_should_alert = False
            except ValueError:
                pass

    all_issues: list[str] = list(disk_issues)
    for item in new_startup:
        all_issues.append(f"Nuevo programa al inicio: {item['name']} ({item['source']})")
    for ev in new_events:
        all_issues.append(f"Error crítico Windows: {ev['provider']} ID={ev['id']} ({ev['time'][:16]})")

    has_alertable_problem = disk_should_alert or bool(new_startup) or bool(new_events)
    log_level = "WARN" if all_issues else "INFO"
    log_line(
        log_level,
        f"disk_issues={len(disk_issues)} new_startup={len(new_startup)} new_critical_events={len(new_events)} "
        f"baseline_init={not was_initialized} dry_run={args.dry_run}",
    )

    notified = False
    if not args.dry_run and (args.force_notify or has_alertable_problem):
        msg = build_telegram_alert(disks, new_startup, new_events, disk_issues if disk_should_alert else [])
        notified = notify_telegram.send_telegram(msg)
        log_line("INFO" if notified else "ERROR", f"notificacion_telegram={notified}")

    if not args.dry_run:
        state["baseline_initialized"] = True
        state["known_startup"] = current_startup
        merged_seen = list(state.get("seen_critical_events", []))
        for ev in new_events:
            if ev.get("key") and ev["key"] not in seen_events:
                merged_seen.append(ev["key"])
        state["seen_critical_events"] = merged_seen[-500:]
        if disk_issues and notified:
            state["last_disk_fingerprint"] = disk_fp
            state["last_disk_alert_at"] = now_iso()
        elif not disk_issues:
            state["last_disk_fingerprint"] = ""
        state["last_run"] = now_iso()
        save_state(state)

    if args.json:
        print(
            json.dumps(
                {
                    "timestamp": now_iso(),
                    "disks": disks,
                    "startup_count": len(current_startup),
                    "new_startup": new_startup,
                    "baseline_created": not was_initialized,
                    "critical_events_new": new_events,
                    "critical_events_total": len(ev_res["events"]),
                    "issues": all_issues,
                    "notified": notified,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(
            format_console_report(
                disks=disks,
                startup_total=len(current_startup),
                new_startup=new_startup,
                baseline_created=not was_initialized,
                new_events=new_events,
                total_events=len(ev_res["events"]),
                days=args.days,
                issues=all_issues,
                dry_run=args.dry_run,
            )
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
