#!/usr/bin/env python3
"""Gestor seguro de Android TV por ADB (Rama 1 - Antigravity-Hub).

Subcomandos:
  - status: verifica conexión, modelo, Android y almacenamiento.
  - backup-list: guarda lista de paquetes instalados/deshabilitados en state/tv-apps.txt.
  - install <ruta_apk>: instala un APK (soporta --dry-run).
  - clean-cache: libera caché de apps de forma segura vía `pm trim-caches` (soporta --dry-run).
  - debloat: deshabilita bloatware conocido usando SOLO `pm disable-user --user 0`
             (con lista blanca de paquetes críticos y --dry-run obligatorio por defecto).
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
STATE_APPS_PATH = ROOT_DIR / "state" / "tv-apps.txt"
LOG_PATH = ROOT_DIR / "logs" / "tv_adb.log"

sys.path.insert(0, str(ROOT_DIR / "scripts" / "common"))
import notify_telegram  # noqa: E402

# Paquetes críticos del sistema que NUNCA se pueden deshabilitar (lista blanca estricta)
PROTECTED_PACKAGES = {
    "android",
    "com.android.systemui",
    "com.android.settings",
    "com.android.tv.settings",
    "com.android.vending",
    "com.google.android.gms",
    "com.google.android.gsf",
    "com.google.android.tvlauncher",
    "com.google.android.apps.tv.launcherx",
    "com.google.android.katniss",
    "com.google.android.inputmethod.latin",
    "com.android.providers.settings",
    "com.android.providers.media",
    "com.android.providers.downloads",
    "com.android.bluetooth",
    "com.android.networkstack",
    "com.android.packageinstaller",
    "com.google.android.packageinstaller",
    "com.android.shell",
}

PROTECTED_PREFIXES = (
    "com.android.providers.",
    "com.android.internal.",
    "com.google.android.networkstack",
)

# Catálogo conservador de bloatware / apps promocionales frecuentes en Android TV
KNOWN_BLOATWARE = [
    "com.google.android.videos",             # Google Play Movies / TV legacy
    "com.google.android.music",              # Google Play Music legacy
    "com.google.android.play.games",         # Google Play Games
    "com.google.android.tvrecommendations",  # Recomendaciones patrocinadas en home
    "com.google.android.marvin.talkback",    # TalkBack (solo si no usás lector de pantalla)
    "com.amazon.amazonvideo.livingroom",     # Prime Video preinstalado
    "com.netflix.ninja",                     # Netflix preinstalado (solo si no lo usás)
    "com.spotify.tv.android",                # Spotify preinstalado (solo si no lo usás)
    "com.facebook.katana",
    "com.facebook.system",
    "com.facebook.appmanager",
    "com.xiaomi.mitv.shop",
    "com.mitv.tvhome.atv",
]

# Por defecto, `debloat` sin --packages solo sugiere los estrictamente promocionales/legacy
DEFAULT_SAFE_DEBLOAT = [
    "com.google.android.videos",
    "com.google.android.music",
    "com.google.android.play.games",
    "com.facebook.katana",
    "com.facebook.system",
    "com.facebook.appmanager",
    "com.xiaomi.mitv.shop",
]


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log_line(level: str, message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"{now_iso()} [{level}] {message}\n")


def find_adb() -> str | None:
    found = shutil.which("adb")
    if found:
        return found
    candidates = [
        Path.home() / "platform-tools" / "adb.exe",
        ROOT_DIR / "tools" / "platform-tools" / "adb.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Android" / "Sdk" / "platform-tools" / "adb.exe",
    ]
    for path in candidates:
        try:
            if path.exists():
                return str(path)
        except OSError:
            continue
    return None


def resolve_target(args: argparse.Namespace) -> str:
    ip = (getattr(args, "ip", "") or "").strip()
    if not ip:
        env = notify_telegram.load_env()
        ip = env.get("TV_IP", "").strip()
    if not ip:
        raise RuntimeError("No se encontró TV_IP en .env ni se indicó --ip.")
    if ":" in ip:
        return ip
    return f"{ip}:{args.port}"


def run_adb(adb_bin: str, args_list: list[str], target: str | None = None, timeout: int = 25) -> tuple[int, str]:
    cmd = [adb_bin]
    if target:
        cmd.extend(["-s", target])
    cmd.extend(args_list)
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
        out = ((res.stdout or "") + "\n" + (res.stderr or "")).strip()
        return res.returncode, out
    except Exception as exc:
        return -1, str(exc)


def ensure_connected(adb_bin: str, target: str) -> tuple[bool, str]:
    rc, conn_out = run_adb(adb_bin, ["connect", target], timeout=12)
    rc_dev, dev_out = run_adb(adb_bin, ["devices"], timeout=10)
    state = "missing"
    for line in dev_out.splitlines():
        parts = line.strip().split()
        if len(parts) >= 2 and parts[0] == target:
            state = parts[1]
            break

    if state == "device":
        return True, f"Conectado a {target}"
    if state == "unauthorized":
        return False, (
            f"TV detectada en {target}, pero está 'unauthorized'. "
            "Aceptá el cartel de autorización de depuración USB/ADB en la pantalla de tu Android TV "
            "(tildá 'Permitir siempre desde esta computadora') y reintentá."
        )
    if state == "offline":
        return False, f"La TV en {target} figura 'offline'. Probá reiniciar Depuración de red en la TV."
    return False, f"No se pudo conectar a {target} (rc={rc}): {conn_out or dev_out}"


def is_protected(pkg: str) -> bool:
    if pkg in PROTECTED_PACKAGES:
        return True
    return any(pkg.startswith(prefix) for prefix in PROTECTED_PREFIXES)


def cmd_status(args: argparse.Namespace, adb_bin: str, target: str) -> int:
    ok, msg = ensure_connected(adb_bin, target)
    if not ok:
        log_line("WARN", f"cmd=status target={target} err={msg}")
        print(msg, file=sys.stderr)
        return 1

    _, brand = run_adb(adb_bin, ["shell", "getprop", "ro.product.manufacturer"], target)
    _, model = run_adb(adb_bin, ["shell", "getprop", "ro.product.model"], target)
    _, android_ver = run_adb(adb_bin, ["shell", "getprop", "ro.build.version.release"], target)
    _, df_out = run_adb(adb_bin, ["shell", "df", "-h", "/data"], target)
    _, pkgs_e = run_adb(adb_bin, ["shell", "pm", "list", "packages", "-e"], target)
    _, pkgs_d = run_adb(adb_bin, ["shell", "pm", "list", "packages", "-d"], target)

    enabled_cnt = len([l for l in pkgs_e.splitlines() if l.startswith("package:")])
    disabled_cnt = len([l for l in pkgs_d.splitlines() if l.startswith("package:")])
    storage_line = df_out.splitlines()[-1] if df_out.splitlines() else "N/D"

    log_line("INFO", f"cmd=status target={target} model={brand} {model} android={android_ver} enabled={enabled_cnt} disabled={disabled_cnt}")
    print(f"=== ANDROID TV ({target}) ===")
    print(f"Equipo:          {brand} {model}".strip())
    print(f"Android:         {android_ver}")
    print(f"Apps activas:    {enabled_cnt} | Deshabilitadas: {disabled_cnt}")
    print(f"Almacenamiento:  {storage_line}")

    if args.notify:
        notify_telegram.send_telegram(
            f"*Android TV ({target})*\nModelo: `{brand} {model}` (Android {android_ver})\n"
            f"Apps activas: `{enabled_cnt}` | Deshabilitadas: `{disabled_cnt}`"
        )
    return 0


def cmd_backup_list(args: argparse.Namespace, adb_bin: str, target: str) -> int:
    ok, msg = ensure_connected(adb_bin, target)
    if not ok:
        log_line("WARN", f"cmd=backup-list target={target} err={msg}")
        print(msg, file=sys.stderr)
        return 1

    rc_e, out_e = run_adb(adb_bin, ["shell", "pm", "list", "packages", "-e"], target, timeout=30)
    rc_d, out_d = run_adb(adb_bin, ["shell", "pm", "list", "packages", "-d"], target, timeout=30)
    if rc_e != 0:
        log_line("ERROR", f"cmd=backup-list rc={rc_e} out={out_e}")
        print(f"Error al listar paquetes: {out_e}", file=sys.stderr)
        return 1

    enabled = sorted(l.replace("package:", "").strip() for l in out_e.splitlines() if l.startswith("package:"))
    disabled = sorted(l.replace("package:", "").strip() for l in out_d.splitlines() if l.startswith("package:"))

    lines = [
        f"# Backup de paquetes Android TV ({target})",
        f"# Fecha: {now_iso()}",
        f"# Habilitados: {len(enabled)} | Deshabilitados: {len(disabled)}",
        "",
        "[ENABLED]",
        *enabled,
        "",
        "[DISABLED]",
        *disabled,
        "",
    ]
    STATE_APPS_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_APPS_PATH.write_text("\n".join(lines), encoding="utf-8")
    log_line("INFO", f"cmd=backup-list target={target} enabled={len(enabled)} disabled={len(disabled)} path={STATE_APPS_PATH}")
    print(f"Lista guardada en {STATE_APPS_PATH} ({len(enabled)} habilitadas, {len(disabled)} deshabilitadas).")
    return 0


def cmd_install(args: argparse.Namespace, adb_bin: str, target: str) -> int:
    apk = Path(args.ruta_apk).expanduser().resolve()
    if not apk.exists() or not apk.is_file():
        print(f"Error: no existe el archivo APK: {apk}", file=sys.stderr)
        return 2
    if apk.suffix.lower() != ".apk":
        print(f"Error: el archivo no tiene extensión .apk: {apk}", file=sys.stderr)
        return 2

    if args.dry_run:
        log_line("INFO", f"cmd=install target={target} apk={apk.name} dry_run=True")
        print(f"[DRY-RUN] Se ejecutaría: {adb_bin} -s {target} install -r \"{apk}\"")
        return 0

    ok, msg = ensure_connected(adb_bin, target)
    if not ok:
        log_line("WARN", f"cmd=install target={target} err={msg}")
        print(msg, file=sys.stderr)
        return 1

    rc, out = run_adb(adb_bin, ["install", "-r", str(apk)], target, timeout=180)
    log_line("INFO" if rc == 0 else "ERROR", f"cmd=install target={target} apk={apk.name} rc={rc}")
    print(out)
    if rc == 0 and args.notify:
        notify_telegram.send_telegram(f"APK `{apk.name}` instalado correctamente en Android TV (`{target}`).")
    return 0 if rc == 0 else rc


def cmd_clean_cache(args: argparse.Namespace, adb_bin: str, target: str) -> int:
    if args.dry_run:
        log_line("INFO", f"cmd=clean-cache target={target} dry_run=True")
        print(f"[DRY-RUN] Se ejecutaría: {adb_bin} -s {target} shell pm trim-caches 999G")
        return 0

    ok, msg = ensure_connected(adb_bin, target)
    if not ok:
        log_line("WARN", f"cmd=clean-cache target={target} err={msg}")
        print(msg, file=sys.stderr)
        return 1

    _, df_before = run_adb(adb_bin, ["shell", "df", "-h", "/data"], target)
    rc, out = run_adb(adb_bin, ["shell", "pm", "trim-caches", "999G"], target, timeout=60)
    _, df_after = run_adb(adb_bin, ["shell", "df", "-h", "/data"], target)
    log_line("INFO" if rc == 0 else "ERROR", f"cmd=clean-cache target={target} rc={rc}")
    print("Antes:  ", df_before.splitlines()[-1] if df_before.splitlines() else "N/D")
    print("Después:", df_after.splitlines()[-1] if df_after.splitlines() else "N/D")
    if out:
        print(out)
    return 0 if rc == 0 else rc


def cmd_debloat(args: argparse.Namespace, adb_bin: str, target: str) -> int:
    # Seguridad estricta: dry-run obligatorio por defecto salvo --apply explícito sin --dry-run
    effective_dry_run = args.dry_run or (not args.apply)

    ok, msg = ensure_connected(adb_bin, target)
    if not ok:
        log_line("WARN", f"cmd=debloat target={target} err={msg}")
        print(msg, file=sys.stderr)
        return 1

    if args.re_enable:
        pkg = args.re_enable.strip()
        if effective_dry_run:
            print(f"[DRY-RUN] Se rehabilitaría: adb -s {target} shell pm enable {pkg}")
            return 0
        rc, out = run_adb(adb_bin, ["shell", "pm", "enable", pkg], target)
        log_line("INFO" if rc == 0 else "ERROR", f"cmd=debloat action=enable pkg={pkg} rc={rc}")
        print(out)
        return 0 if rc == 0 else rc

    rc_e, out_e = run_adb(adb_bin, ["shell", "pm", "list", "packages", "-e"], target, timeout=30)
    if rc_e != 0:
        print(f"No se pudieron listar paquetes activos: {out_e}", file=sys.stderr)
        return 1
    installed_enabled = {l.replace("package:", "").strip() for l in out_e.splitlines() if l.startswith("package:")}

    candidates = args.packages if args.packages else DEFAULT_SAFE_DEBLOAT
    blocked: list[str] = []
    targets: list[str] = []
    for pkg in candidates:
        if is_protected(pkg):
            blocked.append(pkg)
        elif pkg in installed_enabled:
            targets.append(pkg)

    if blocked:
        print("BLOQUEADOS por lista blanca de sistema (nunca se deshabilitan):", ", ".join(blocked))

    if not targets:
        log_line("INFO", f"cmd=debloat target={target} dry_run={effective_dry_run} candidates=0")
        print("No se encontraron paquetes candidatos habilitados en la TV.")
        return 0

    if effective_dry_run:
        log_line("INFO", f"cmd=debloat target={target} dry_run=True targets={','.join(targets)}")
        print(f"[DRY-RUN] Se deshabilitarían ({len(targets)}) con `pm disable-user --user 0` (reversible):")
        for pkg in targets:
            print(f"  - pm disable-user --user 0 {pkg}")
        print("\nPara aplicar realmente, repetí con `--apply` (nunca se desinstala definitivamente).")
        return 0

    disabled_ok: list[str] = []
    for pkg in targets:
        rc, out = run_adb(adb_bin, ["shell", "pm", "disable-user", "--user", "0", pkg], target)
        log_line("INFO" if rc == 0 else "ERROR", f"cmd=debloat action=disable-user pkg={pkg} rc={rc} out={out}")
        print(f"{pkg}: {out}")
        if rc == 0:
            disabled_ok.append(pkg)

    if args.notify and disabled_ok:
        notify_telegram.send_telegram(
            f"*Android TV Debloat (`{target}`)*\nDeshabilitados con `pm disable-user`: "
            + ", ".join(f"`{p}`" for p in disabled_ok)
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Gestor seguro de Android TV por ADB (Rama 1 - Antigravity-Hub).")
    parser.add_argument("--ip", default="", help="IP de la Android TV (por defecto usa TV_IP de .env).")
    parser.add_argument("--port", type=int, default=5555, help="Puerto ADB (default: 5555).")
    sub = parser.add_subparsers(dest="command", required=True)

    p_st = sub.add_parser("status", help="Verifica conexión y estado general de la TV.")
    p_st.add_argument("--notify", action="store_true", help="Enviar resumen por Telegram.")
    p_st.set_defaults(func=cmd_status)

    p_bk = sub.add_parser("backup-list", help="Guarda lista de paquetes en state/tv-apps.txt.")
    p_bk.set_defaults(func=cmd_backup_list)

    p_in = sub.add_parser("install", help="Instala un archivo APK en la Android TV.")
    p_in.add_argument("ruta_apk", help="Ruta local al archivo .apk.")
    p_in.add_argument("--dry-run", action="store_true", help="Simula sin instalar.")
    p_in.add_argument("--notify", action="store_true", help="Avisar por Telegram al completar.")
    p_in.set_defaults(func=cmd_install)

    p_cc = sub.add_parser("clean-cache", help="Limpia caché de apps con `pm trim-caches`.")
    p_cc.add_argument("--dry-run", action="store_true", help="Simula sin limpiar caché.")
    p_cc.set_defaults(func=cmd_clean_cache)

    p_db = sub.add_parser("debloat", help="Deshabilita bloatware usando solo `pm disable-user` (dry-run por defecto).")
    p_db.add_argument("--packages", nargs="+", help="Lista específica de paquetes a evaluar.")
    p_db.add_argument("--re-enable", default="", help="Rehabilita un paquete previamente deshabilitado.")
    p_db.add_argument("--dry-run", action="store_true", help="Fuerza modo simulación.")
    p_db.add_argument("--apply", action="store_true", help="Aplica `pm disable-user --user 0` (reversible).")
    p_db.add_argument("--notify", action="store_true", help="Avisar por Telegram.")
    p_db.set_defaults(func=cmd_debloat)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    adb_bin = find_adb()
    if not adb_bin:
        print("Error: no se encontró `adb.exe` en PATH ni en %USERPROFILE%\\platform-tools.", file=sys.stderr)
        return 1
    try:
        target = resolve_target(args)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return args.func(args, adb_bin, target)


if __name__ == "__main__":
    sys.exit(main())
