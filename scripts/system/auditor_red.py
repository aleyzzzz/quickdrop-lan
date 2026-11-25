#!/usr/bin/env python3
"""Auditor de red local y diagnóstico de conectividad (Rama 5 - Antigravity-Hub).

Solo lectura: no modifica configuración de red, firewall ni Registro de Windows.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT_DIR / "state" / "auditor_red.json"
LOG_PATH = ROOT_DIR / "logs" / "auditor_red.log"

sys.path.insert(0, str(ROOT_DIR / "scripts" / "common"))
import notify_telegram  # noqa: E402


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log_line(level: str, message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"{now_iso()} [{level}] {message}\n")


def run_cmd(cmd: list[str], timeout: int = 12) -> tuple[int, str]:
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="cp850",
            errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return res.returncode, (res.stdout or "") + (res.stderr or "")
    except Exception as exc:
        return -1, str(exc)


def detect_network_info() -> dict[str, Any]:
    """Detecta IP local, máscara, puerta de enlace (router), interfaz y DNS."""
    info: dict[str, Any] = {
        "hostname": socket.gethostname(),
        "interface": "",
        "local_ip": "",
        "netmask": "255.255.255.0",
        "gateway": "",
        "mac": "",
        "dns_servers": [],
    }

    # 1) Detectar IP local y gateway desde `route print 0.0.0.0`
    rc, route_out = run_cmd(["route", "print", "0.0.0.0"], timeout=10)
    if rc == 0:
        best_metric = 10**9
        for line in route_out.splitlines():
            m = re.match(
                r"^\s*0\.0\.0\.0\s+0\.0\.0\.0\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+\.\d+\.\d+\.\d+)\s+(\d+)",
                line,
            )
            if m:
                gw, iface_ip, metric = m.group(1), m.group(2), int(m.group(3))
                if metric < best_metric:
                    best_metric = metric
                    info["gateway"] = gw
                    info["local_ip"] = iface_ip

    # Fallback de IP local por socket UDP si route no devolvió nada
    if not info["local_ip"]:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("1.1.1.1", 80))
                info["local_ip"] = s.getsockname()[0]
        except OSError:
            pass

    # 2) Enriquecer con `ipconfig /all` (soporta Windows en español e inglés)
    rc, ipcfg = run_cmd(["ipconfig", "/all"], timeout=10)
    if rc == 0:
        blocks = re.split(r"\r?\n(?=\S.*:\s*$)", ipcfg, flags=re.MULTILINE)
        chosen_block = ""
        for block in blocks:
            if info["local_ip"] and info["local_ip"] in block:
                chosen_block = block
                break
        if not chosen_block:
            for block in blocks:
                if re.search(r"(Puerta de enlace|Default Gateway).*?:\s*\d+\.\d+\.\d+\.\d+", block, re.I):
                    chosen_block = block
                    break

        if chosen_block:
            first_line = chosen_block.splitlines()[0].strip().rstrip(":")
            info["interface"] = first_line

            if not info["local_ip"]:
                m = re.search(r"(?:Direcci.n IPv4|IPv4 Address)[^:]*:\s*(\d+\.\d+\.\d+\.\d+)", chosen_block, re.I)
                if m:
                    info["local_ip"] = m.group(1)

            m_mask = re.search(r"(?:M.scara de subred|Subnet Mask)[^:]*:\s*(\d+\.\d+\.\d+\.\d+)", chosen_block, re.I)
            if m_mask:
                info["netmask"] = m_mask.group(1)

            m_mac = re.search(r"(?:Direcci.n f.sica|Physical Address)[^:]*:\s*([0-9A-Fa-f-]{17})", chosen_block, re.I)
            if m_mac:
                info["mac"] = m_mac.group(1).lower()

            if not info["gateway"]:
                gw_matches = re.findall(
                    r"(?:Puerta de enlace predeterminada|Default Gateway)[^:]*:\s*([^\r\n]+(?:\r?\n\s+[^\r\n]+)*)",
                    chosen_block,
                    re.I,
                )
                for chunk in gw_matches:
                    ips = re.findall(r"\b(\d+\.\d+\.\d+\.\d+)\b", chunk)
                    if ips:
                        info["gateway"] = ips[0]
                        break

            dns_matches = re.findall(
                r"(?:Servidores DNS|DNS Servers)[^:]*:\s*([^\r\n]+(?:\r?\n\s+(?!\S+\s*\.)[^\r\n]+)*)",
                chosen_block,
                re.I,
            )
            dns_list: list[str] = []
            for chunk in dns_matches:
                for addr in re.findall(r"\b(\d+\.\d+\.\d+\.\d+|[0-9a-fA-F:]+:[0-9a-fA-F:]+)\b", chunk):
                    if addr not in dns_list:
                        dns_list.append(addr)
            info["dns_servers"] = dns_list

    return info


def ping_host(host: str, count: int = 3, timeout_ms: int = 1000) -> dict[str, Any]:
    rc, out = run_cmd(["ping", "-n", str(count), "-w", str(timeout_ms), host], timeout=max(8, count * 3))
    result: dict[str, Any] = {
        "target": host,
        "reachable": False,
        "loss_pct": 100,
        "avg_ms": None,
        "raw_error": "",
    }
    if rc < 0:
        result["raw_error"] = out
        return result

    # Parse packet loss: "(0% perdidos)" o "(0% loss)"
    m_loss = re.search(r"\((\d+)%\s*(?:perdidos|loss)", out, re.I)
    if m_loss:
        result["loss_pct"] = int(m_loss.group(1))
    else:
        # Fallback: contar respuestas TTL=
        ttl_hits = len(re.findall(r"TTL=\d+", out, re.I))
        if ttl_hits > 0:
            result["loss_pct"] = round((1 - ttl_hits / count) * 100)

    # Parse average latency: "Media = 2ms" o "Average = 2ms"
    m_avg = re.search(r"(?:Media|Average)\s*=\s*(\d+)\s*ms", out, re.I)
    if m_avg:
        result["avg_ms"] = int(m_avg.group(1))
    else:
        times = [int(x) for x in re.findall(r"(?:tiempo|time)[<=](\d+)\s*ms", out, re.I)]
        if times:
            result["avg_ms"] = round(sum(times) / len(times))

    result["reachable"] = result["loss_pct"] < 100
    if not result["reachable"] and not m_loss:
        result["raw_error"] = out.strip().splitlines()[0] if out.strip() else "Sin respuesta"
    return result


def tcp_check(host: str, port: int, timeout: float = 3.0) -> tuple[bool, int | None]:
    t0 = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            elapsed = round((time.perf_counter() - t0) * 1000)
            return True, elapsed
    except OSError:
        return False, None


def check_dns(domains: tuple[str, ...] = ("google.com", "cloudflare.com")) -> dict[str, Any]:
    resolved: dict[str, list[str]] = {}
    timings: list[int] = []
    errors: list[str] = []

    for dom in domains:
        t0 = time.perf_counter()
        try:
            infos = socket.getaddrinfo(dom, 443, type=socket.SOCK_STREAM)
            elapsed = round((time.perf_counter() - t0) * 1000)
            ips = sorted({item[4][0] for item in infos})
            resolved[dom] = ips[:3]
            timings.append(elapsed)
        except OSError as exc:
            errors.append(f"{dom}: {exc}")

    return {
        "ok": len(resolved) > 0,
        "resolved": resolved,
        "avg_ms": round(sum(timings) / len(timings)) if timings else None,
        "errors": errors,
    }


def check_https(url: str = "https://www.google.com/generate_204", timeout: float = 5.0) -> dict[str, Any]:
    t0 = time.perf_counter()
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "Antigravity-Hub-Auditor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed = round((time.perf_counter() - t0) * 1000)
            return {"ok": 200 <= resp.status < 400, "status": resp.status, "ms": elapsed, "error": ""}
    except urllib.error.HTTPError as exc:
        elapsed = round((time.perf_counter() - t0) * 1000)
        return {"ok": 200 <= exc.code < 400, "status": exc.code, "ms": elapsed, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "status": None, "ms": None, "error": str(exc)}


def diagnose_connectivity(net: dict[str, Any]) -> dict[str, Any]:
    gateway = net.get("gateway", "")
    router_ping = ping_host(gateway, count=3, timeout_ms=800) if gateway else {
        "target": "",
        "reachable": False,
        "loss_pct": 100,
        "avg_ms": None,
        "raw_error": "No se detectó puerta de enlace predeterminada",
    }

    ip_ping_1 = ping_host("1.1.1.1", count=3, timeout_ms=1000)
    ip_ping_2 = ping_host("8.8.8.8", count=2, timeout_ms=1000) if not ip_ping_1["reachable"] else None
    tcp_cf_ok, tcp_cf_ms = tcp_check("1.1.1.1", 443, timeout=3.0)

    internet_ip_ok = bool(
        ip_ping_1["reachable"]
        or (ip_ping_2 and ip_ping_2["reachable"])
        or tcp_cf_ok
    )
    internet_avg_ms = ip_ping_1["avg_ms"] or (ip_ping_2["avg_ms"] if ip_ping_2 else None) or tcp_cf_ms
    internet_loss_pct = ip_ping_1["loss_pct"] if ip_ping_1["reachable"] else (
        ip_ping_2["loss_pct"] if (ip_ping_2 and ip_ping_2["reachable"]) else (0 if tcp_cf_ok else 100)
    )

    dns_res = check_dns()
    https_res = check_https()

    warnings: list[str] = []
    if not gateway or not router_ping["reachable"]:
        status = "ERROR_ROUTER"
        healthy = False
        diagnosis = (
            f"Problema en red local / Wi-Fi o router: no responde la puerta de enlace ({gateway or 'sin gateway'}). "
            "Revisá cable/Wi-Fi o reiniciá el router."
        )
    elif not internet_ip_ok:
        status = "ERROR_INTERNET"
        healthy = False
        diagnosis = (
            f"Tu router ({gateway}) responde bien ({router_ping['avg_ms']} ms), pero no hay salida a Internet "
            "(1.1.1.1 y 8.8.8.8 no responden). El corte es del proveedor (ISP) o del módem."
        )
    elif not dns_res["ok"]:
        status = "ERROR_DNS"
        healthy = False
        diagnosis = (
            "Tu router y la salida a Internet por IP funcionan, pero falla la resolución DNS. "
            "Cambiá los DNS a 1.1.1.1 / 8.8.8.8 o reiniciá el servicio/router."
        )
    elif not https_res["ok"]:
        status = "ERROR_HTTPS"
        healthy = False
        diagnosis = (
            "Router, salida IP y DNS funcionan, pero falló la conexión HTTPS. "
            f"Posible portal cautivo, firewall o proxy/VPN ({https_res['error']})."
        )
    else:
        status = "OK"
        healthy = True
        diagnosis = (
            f"Red saludable: router ({router_ping['avg_ms']} ms), Internet IP ({internet_avg_ms} ms), "
            f"DNS ({dns_res['avg_ms']} ms) y HTTPS ({https_res['ms']} ms) funcionando correctamente."
        )

    if router_ping["reachable"] and router_ping["loss_pct"] > 0:
        warnings.append(f"Pérdida de paquetes al router: {router_ping['loss_pct']}%")
    if router_ping["avg_ms"] is not None and router_ping["avg_ms"] > 50:
        warnings.append(f"Latencia alta hacia el router: {router_ping['avg_ms']} ms")
    if internet_ip_ok and internet_loss_pct > 0:
        warnings.append(f"Pérdida de paquetes a Internet: {internet_loss_pct}%")
    if internet_avg_ms is not None and internet_avg_ms > 150:
        warnings.append(f"Latencia alta hacia Internet: {internet_avg_ms} ms")

    if healthy and warnings:
        status = "DEGRADED"

    return {
        "status": status,
        "healthy": healthy,
        "diagnosis": diagnosis,
        "warnings": warnings,
        "router": router_ping,
        "internet_ip": {
            "ok": internet_ip_ok,
            "avg_ms": internet_avg_ms,
            "loss_pct": internet_loss_pct,
            "ping_1_1_1_1": ip_ping_1,
            "tcp_1_1_1_1_443_ms": tcp_cf_ms,
        },
        "dns": dns_res,
        "https": https_res,
    }


def _ping_quiet(ip: str) -> None:
    try:
        subprocess.run(
            ["ping", "-n", "1", "-w", "350", ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def _resolve_hostname(ip: str) -> str:
    try:
        name = socket.gethostbyaddr(ip)[0]
        return name
    except Exception:
        return ""


def scan_lan_devices(net: dict[str, Any]) -> list[dict[str, Any]]:
    local_ip = net.get("local_ip", "")
    netmask = net.get("netmask", "255.255.255.0")
    gateway = net.get("gateway", "")
    if not local_ip:
        return []

    try:
        network = ipaddress.IPv4Network(f"{local_ip}/{netmask}", strict=False)
    except ValueError:
        network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)

    # Limitar barrido a un /24 centrado en la IP local si la subred fuera más grande
    if network.num_addresses > 256:
        network = ipaddress.IPv4Network(f"{local_ip}/24", strict=False)

    hosts = [str(h) for h in network.hosts() if str(h) != local_ip]
    with concurrent.futures.ThreadPoolExecutor(max_workers=64) as ex:
        list(ex.map(_ping_quiet, hosts))

    rc, arp_out = run_cmd(["arp", "-a"], timeout=10)
    devices_by_ip: dict[str, dict[str, Any]] = {}

    if rc == 0:
        in_target_iface = False
        for line in arp_out.splitlines():
            m_iface = re.match(r"^\s*(?:Interfaz|Interface):\s*(\d+\.\d+\.\d+\.\d+)", line, re.I)
            if m_iface:
                in_target_iface = (m_iface.group(1) == local_ip)
                continue
            if not in_target_iface:
                continue
            m_entry = re.match(
                r"^\s*(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F]{2}(?:-[0-9a-fA-F]{2}){5})\s+(\S+)",
                line,
            )
            if not m_entry:
                continue
            ip_str, mac_str, entry_type = m_entry.group(1), m_entry.group(2).lower(), m_entry.group(3)
            try:
                ip_obj = ipaddress.IPv4Address(ip_str)
            except ValueError:
                continue
            if ip_obj not in network or ip_obj == network.broadcast_address or ip_obj.is_multicast:
                continue
            if mac_str == "ff-ff-ff-ff-ff-ff":
                continue
            devices_by_ip[ip_str] = {
                "ip": ip_str,
                "mac": mac_str,
                "type": entry_type,
                "hostname": "",
                "role": "Router" if ip_str == gateway else "Equipo",
            }

    # Incluir esta PC en la lista
    devices_by_ip[local_ip] = {
        "ip": local_ip,
        "mac": net.get("mac", ""),
        "type": "local",
        "hostname": net.get("hostname", socket.gethostname()),
        "role": "Esta PC",
    }

    # Resolución de hostnames en paralelo para no demorar
    ips_to_resolve = [ip for ip, d in devices_by_ip.items() if not d["hostname"]]
    if ips_to_resolve:
        with concurrent.futures.ThreadPoolExecutor(max_workers=16) as ex:
            future_map = {ex.submit(_resolve_hostname, ip): ip for ip in ips_to_resolve}
            for fut in concurrent.futures.as_completed(future_map):
                ip = future_map[fut]
                try:
                    devices_by_ip[ip]["hostname"] = fut.result()
                except Exception:
                    pass

    return sorted(devices_by_ip.values(), key=lambda d: tuple(int(p) for p in d["ip"].split(".")))


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"baseline_initialized": False, "known_macs": {}, "last_status": "OK", "last_run": ""}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def reconcile_devices(
    devices: list[dict[str, Any]], state: dict[str, Any], dry_run: bool
) -> tuple[list[dict[str, Any]], bool]:
    known: dict[str, Any] = state.get("known_macs", {})
    was_initialized = bool(state.get("baseline_initialized", False))
    new_devices: list[dict[str, Any]] = []
    ts = now_iso()

    for dev in devices:
        mac = dev.get("mac", "")
        if not mac:
            continue
        if mac not in known:
            if was_initialized:
                dev["is_new"] = True
                new_devices.append(dev)
            else:
                dev["is_new"] = False
            known[mac] = {
                "first_seen": ts,
                "last_seen": ts,
                "ip": dev["ip"],
                "hostname": dev["hostname"],
                "role": dev["role"],
            }
        else:
            dev["is_new"] = False
            known[mac]["last_seen"] = ts
            known[mac]["ip"] = dev["ip"]
            if dev["hostname"]:
                known[mac]["hostname"] = dev["hostname"]

    if not dry_run and devices:
        state["known_macs"] = known
        state["baseline_initialized"] = True
    return new_devices, not was_initialized


def _fmt_ms(val: int | None) -> str:
    return f"{val}ms" if val is not None else "N/D"


def format_console_report(
    net: dict[str, Any],
    diag: dict[str, Any],
    devices: list[dict[str, Any]],
    new_devices: list[dict[str, Any]],
    baseline_created: bool,
    dry_run: bool = False,
) -> str:
    lines = [
        "=== AUDITOR DE RED LOCAL (Antigravity-Hub) ===",
        f"Fecha:     {now_iso()}",
        f"Interfaz:  {net.get('interface') or 'N/D'}",
        f"IP local:  {net.get('local_ip') or 'N/D'} ({net.get('hostname')})",
        f"Router:    {net.get('gateway') or 'N/D'}",
        f"DNS:       {', '.join(net.get('dns_servers') or []) or 'Automático / sistema'}",
        "",
        "--- Pruebas de conectividad ---",
        f"1. Router ({diag['router']['target'] or 'N/D'}): "
        f"{'OK' if diag['router']['reachable'] else 'FALLA'} "
        f"(avg={_fmt_ms(diag['router']['avg_ms'])}, loss={diag['router']['loss_pct']}%)",
        f"2. Internet IP (1.1.1.1): "
        f"{'OK' if diag['internet_ip']['ok'] else 'FALLA'} "
        f"(avg={_fmt_ms(diag['internet_ip']['avg_ms'])}, loss={diag['internet_ip']['loss_pct']}%)",
        f"3. DNS: "
        f"{'OK' if diag['dns']['ok'] else 'FALLA'} "
        f"(avg={_fmt_ms(diag['dns']['avg_ms'])})",
        f"4. HTTPS: "
        f"{'OK' if diag['https']['ok'] else 'FALLA'} "
        f"(status={diag['https']['status'] or 'N/D'}, {_fmt_ms(diag['https']['ms'])})",
        "",
        f"DIAGNÓSTICO [{diag['status']}]: {diag['diagnosis']}",
    ]
    if diag["warnings"]:
        lines.append("Advertencias: " + " | ".join(diag["warnings"]))

    if devices:
        lines.append("")
        lines.append(f"--- Equipos conectados en la red local ({len(devices)}) ---")
        lines.append(f"{'IP':<16} {'MAC':<19} {'Rol':<10} {'Hostname'}")
        lines.append("-" * 68)
        for d in devices:
            tag = " [NUEVO]" if d.get("is_new") else ""
            lines.append(
                f"{d['ip']:<16} {(d['mac'] or '-'):<19} {d['role']:<10} {(d['hostname'] or '-')}{tag}"
            )
        if baseline_created:
            if dry_run:
                lines.append("\nNota (dry-run): se crearía la línea base de equipos conocidos en state/auditor_red.json.")
            else:
                lines.append("\nNota: se creó la línea base de equipos conocidos en state/auditor_red.json.")
        elif new_devices:
            lines.append(f"\nALERTA: {len(new_devices)} equipo(s) nuevo(s) detectado(s) en la red.")

    return "\n".join(lines)


def build_telegram_message(diag: dict[str, Any], devices: list[dict[str, Any]], new_devices: list[dict[str, Any]]) -> str:
    parts = [f"*Auditor de Red ({diag['status']})*", diag["diagnosis"]]
    if diag["warnings"]:
        parts.append("Avisos: " + "; ".join(diag["warnings"]))
    if new_devices:
        parts.append(f"\n*Equipos nuevos detectados ({len(new_devices)}):*")
        for d in new_devices[:8]:
            host = f" ({d['hostname']})" if d["hostname"] else ""
            parts.append(f"- `{d['ip']}` | `{d['mac']}`{host}")
    elif devices:
        parts.append(f"Equipos activos en LAN: {len(devices)}")
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser(description="Auditor de red local y conectividad (Rama 5).")
    parser.add_argument("--no-scan", action="store_true", help="Omitir el barrido de equipos en la LAN.")
    parser.add_argument("--notify", action="store_true", help="Notificar por Telegram solo si hay anomalías o equipos nuevos.")
    parser.add_argument("--force-notify", action="store_true", help="Enviar resumen por Telegram aunque todo esté OK.")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin guardar estado ni enviar alertas a Telegram.")
    parser.add_argument("--json", action="store_true", help="Imprimir salida en formato JSON.")
    args = parser.parse_args()

    net = detect_network_info()
    diag = diagnose_connectivity(net)
    devices = [] if args.no_scan else scan_lan_devices(net)

    state = load_state()
    new_devices, baseline_created = reconcile_devices(devices, state, dry_run=args.dry_run)

    has_problem = (not diag["healthy"]) or bool(diag["warnings"]) or bool(new_devices)
    log_level = "WARN" if has_problem else "INFO"
    log_line(
        log_level,
        f"status={diag['status']} gateway={net.get('gateway')} devices={len(devices)} "
        f"new_devices={len(new_devices)} dry_run={args.dry_run} | {diag['diagnosis']}",
    )

    notified = False
    should_notify = (args.force_notify or (args.notify and has_problem)) and not args.dry_run
    # Evitar duplicar la misma alerta de conectividad si nada cambió y no hay equipos nuevos
    if args.notify and not args.force_notify and not new_devices and state.get("last_status") == diag["status"] and diag["status"] != "OK":
        should_notify = False

    if should_notify:
        msg = build_telegram_message(diag, devices, new_devices)
        notified = notify_telegram.send_telegram(msg)
        log_line("INFO" if notified else "ERROR", f"notificacion_telegram={notified}")

    if not args.dry_run:
        state["last_status"] = diag["status"]
        state["last_run"] = now_iso()
        save_state(state)

    payload = {
        "timestamp": now_iso(),
        "network": net,
        "diagnostics": diag,
        "devices": devices,
        "new_devices": new_devices,
        "notified": notified,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(format_console_report(net, diag, devices, new_devices, baseline_created, dry_run=args.dry_run))

    return 0 if diag["healthy"] else 1


if __name__ == "__main__":
    sys.exit(main())
