#!/usr/bin/env python3
"""Pipeline de organización de descargas multimedia y nube (Rama 1 - Antigravity-Hub).

- Vigila carpetas configuradas en DOWNLOADS_DIR ignorando archivos en curso (.part, .!qB, .tmp, etc.).
- Normaliza nombres de Series (`Series/<Nombre>/Season XX/<Nombre> - SXXEXX.<ext>`)
  y Películas (`Peliculas/<Nombre> (YYYY)/<Nombre> (YYYY).<ext>`), incluyendo subtítulos acompañantes.
- Con `--dry-run` solo simula (no mueve archivos, no escribe state/ ni avisa a Telegram).
- Sin `--dry-run` mueve los archivos de forma segura (sin sobrescribir ni borrar),
  sincroniza incrementalmente con `rclone copy` si `rclone` y el remoto existen,
  y avisa por Telegram qué títulos nuevos quedaron listos (modo silencioso si no hay novedades).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
STATE_PATH = ROOT_DIR / "state" / "organizar_media.json"
LOG_PATH = ROOT_DIR / "logs" / "organizar_media.log"

sys.path.insert(0, str(ROOT_DIR / "scripts" / "common"))
import notify_telegram  # noqa: E402

VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".ts", ".webm"}
SUB_EXTS = {".srt", ".ass", ".ssa", ".sub", ".vtt"}
IN_PROGRESS_EXTS = {".part", ".!qb", ".tmp", ".crdownload", ".downloading", ".aria2", ".bc!", ".utpart"}

# Códigos frecuentes en carpetas de descarga cuyo nombre real de serie ya es conocido
FOLDER_SERIES_ALIASES = {
    "BN0510": "Ben 10",
    "CR99JLP": "Courage The Cowardly Dog",
    "DR1507MTT": "Drama Total",
    "DV6010NTR": "Hora de Aventura",
    "MD8U10": "MAD",
    "NS10HWM": "Un Show Más",
}

RELEASE_TAG_RE = re.compile(
    r"\b("
    r"2160p|1080p|720p|480p|4k|uhd|hdr10\+?|hdr|dv|dolby\.?vision|"
    r"web-?dl|webrip|bluray|blu-?ray|bdrip|brrip|hdrip|dvdrip|hdtv|remux|"
    r"x264|x265|h\.?264|h\.?265|hevc|av1|xvid|10bit|8bit|"
    r"aac\d*\.?\d*|ac3|eac3|ddp?\d*\.?\d*|dts(?:-hd)?|truehd|atmos|flac|mp3|"
    r"dual|latino|castellano|espa[nñ]ol|multi|subtitulado|subbed|dubbed|"
    r"repack|proper|extended|unrated|directors\.?cut|nf|amzn|dsnp|hmax|atvp|yts|rarbg|eztv|ettv|hd"
    r")\b",
    re.IGNORECASE,
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log_line(level: str, message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"{now_iso()} [{level}] {message}\n")


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .-_")
    return cleaned or "Sin Titulo"


def clean_title_fragment(raw: str) -> str:
    text = re.sub(r"\[[^\]]*\]", " ", raw)
    text = re.sub(r"\([^\)]*(?:1080p|720p|2160p|web|bluray|bdrip|x264|x265|hevc|sub)[^\)]*\)", " ", text, flags=re.I)
    text = re.sub(r"[._]+", " ", text)
    m_tag = RELEASE_TAG_RE.search(text)
    if m_tag:
        text = text[: m_tag.start()]
    text = re.sub(r"[\s\-–]+$", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return "Sin Titulo"
    words = []
    small_words = {"de", "del", "la", "las", "el", "los", "y", "of", "the", "and", "in", "on", "to", "a"}
    for idx, w in enumerate(text.split()):
        if idx > 0 and w.lower() in small_words:
            words.append(w.lower())
        elif w.isupper() and len(w) <= 4:
            words.append(w)
        else:
            words.append(w[0].upper() + w[1:].lower() if len(w) > 1 else w.upper())
    return sanitize_filename(" ".join(words))


def infer_show_and_season_from_parents(file_path: Path, stop_roots: list[Path]) -> tuple[str, int | None]:
    """Busca nombre de serie y temporada en las carpetas padre cuando el archivo no trae el título."""
    season: int | None = None
    candidates: list[str] = []
    stop_resolved = {r.resolve() for r in stop_roots}

    for parent in file_path.parents:
        try:
            if parent.resolve() in stop_resolved:
                break
        except OSError:
            break
        pname = parent.name.strip()
        if not pname or pname.lower() in ("series", "peliculas", "otros"):
            continue
        m_s = re.search(r"\b(?:Season|Temporada|T)\s*0*(\d{1,2})\b", pname, re.I)
        if m_s and season is None:
            season = int(m_s.group(1))
        # Limpiar sufijos de temporada/rango de episodios (ej. "DR1507MTT T2 E01 - 26")
        base = re.sub(r"\b(?:Season|Temporada|T)\s*\d{1,2}.*$", "", pname, flags=re.I).strip(" -_")
        if base:
            candidates.append(base)

    for raw in candidates:
        upper = raw.upper().strip()
        if upper in FOLDER_SERIES_ALIASES:
            return FOLDER_SERIES_ALIASES[upper], season
    if candidates:
        raw = candidates[0]
        if raw.isupper() and any(ch.isdigit() for ch in raw) and len(raw) <= 12:
            return raw, season
        return clean_title_fragment(raw), season
    return "Sin Titulo", season


def classify_media(file_path: Path, dest_root: Path, source_roots: list[Path]) -> dict[str, Any]:
    stem = file_path.stem
    ext = file_path.suffix.lower()

    # 1) Series: S01E02, 1x02, 6x313, 8x19-20, 01X01
    m_ser = re.search(
        r"(?:^|[\s._\-])(?:S(\d{1,2})E(\d{1,3})(?:-?E(\d{1,3}))?|(\d{1,2})[xX](\d{1,3})(?:-(\d{1,3}))?)(?:$|[\s._\-])",
        stem,
        re.I,
    )
    if m_ser:
        if m_ser.group(1) is not None:
            season = int(m_ser.group(1))
            ep = int(m_ser.group(2))
            ep2 = int(m_ser.group(3)) if m_ser.group(3) else None
        else:
            season = int(m_ser.group(4))
            ep = int(m_ser.group(5))
            ep2 = int(m_ser.group(6)) if m_ser.group(6) else None

        ep_code = f"S{season:02d}E{ep:02d}" + (f"-E{ep2:02d}" if ep2 else "")
        show_raw = stem[: m_ser.start()].strip(" -._")
        if show_raw:
            show_name = clean_title_fragment(show_raw)
        else:
            show_name, _ = infer_show_and_season_from_parents(file_path, source_roots + [dest_root])
        rel_dir = Path("Series") / show_name / f"Season {season:02d}"
        new_base = f"{show_name} - {ep_code}"
        return {
            "kind": "serie",
            "title": f"{show_name} {ep_code}",
            "dest_path": dest_root / rel_dir / f"{new_base}{ext}",
            "new_base": new_base,
        }

    # 1b) Episodios numerados tipo "01 - Título" dentro de carpeta con temporada (ej. "DR1507MTT T2 E01 - 26")
    m_num_ep = re.match(r"^(\d{1,3})\s*-\s*(.+)$", stem)
    if m_num_ep:
        parent_show, parent_season = infer_show_and_season_from_parents(file_path, source_roots + [dest_root])
        if parent_season is not None and parent_show != "Sin Titulo":
            ep = int(m_num_ep.group(1))
            ep_code = f"S{parent_season:02d}E{ep:02d}"
            rel_dir = Path("Series") / parent_show / f"Season {parent_season:02d}"
            new_base = f"{parent_show} - {ep_code}"
            return {
                "kind": "serie",
                "title": f"{parent_show} {ep_code}",
                "dest_path": dest_root / rel_dir / f"{new_base}{ext}",
                "new_base": new_base,
            }

    # 1c) Episodios anime tipo "[Grupo] Serie 13 [1080p]"
    m_anime = re.match(r"^(?:\[[^\]]+\]\s*)?(.+?)\s+(\d{1,3})\s*(?:\[|\(|$)", stem)
    if m_anime and not re.match(r"^(19\d{2}|20\d{2})$", m_anime.group(2)):
        show_name = clean_title_fragment(m_anime.group(1))
        ep = int(m_anime.group(2))
        ep_code = f"S01E{ep:02d}"
        rel_dir = Path("Series") / show_name / "Season 01"
        new_base = f"{show_name} - {ep_code}"
        return {
            "kind": "serie",
            "title": f"{show_name} {ep_code}",
            "dest_path": dest_root / rel_dir / f"{new_base}{ext}",
            "new_base": new_base,
        }

    # 2) Películas: año (1920-2039)
    m_yr = re.search(r"(?:^|[\s._\-\(\[])((?:19[2-9]\d|20[0-3]\d))(?:$|[\s._\-\)\]])", stem)
    if m_yr:
        year = m_yr.group(1)
        movie_raw = stem[: m_yr.start()].strip(" -._")
        if not movie_raw:
            movie_raw = file_path.parent.name
        movie_name = clean_title_fragment(movie_raw)
        folder_name = f"{movie_name} ({year})"
        rel_dir = Path("Peliculas") / folder_name
        return {
            "kind": "pelicula",
            "title": folder_name,
            "dest_path": dest_root / rel_dir / f"{folder_name}{ext}",
            "new_base": folder_name,
        }

    # 3) Fallback seguro (sin borrar ni perder nada)
    clean_name = clean_title_fragment(stem)
    return {
        "kind": "otro",
        "title": clean_name,
        "dest_path": dest_root / "Otros" / f"{clean_name}{ext}",
        "new_base": clean_name,
    }


def has_in_progress_sibling(file_path: Path) -> bool:
    name_lower = file_path.name.lower()
    for ext in IN_PROGRESS_EXTS:
        if name_lower.endswith(ext):
            return True
    parent = file_path.parent
    for ext in (".part", ".!qB", ".!qb", ".tmp", ".crdownload", ".aria2"):
        try:
            if (parent / (file_path.name + ext)).exists():
                return True
        except OSError:
            continue
    return False


def find_companion_subtitles(video_path: Path) -> list[tuple[Path, str]]:
    """Encuentra subtítulos en la misma carpeta que empiecen con el mismo stem del video."""
    subs: list[tuple[Path, str]] = []
    v_stem_lower = video_path.stem.lower()
    try:
        for cand in video_path.parent.iterdir():
            if not cand.is_file() or cand.suffix.lower() not in SUB_EXTS:
                continue
            c_stem = cand.stem
            if c_stem.lower() == v_stem_lower:
                subs.append((cand, ""))
            elif c_stem.lower().startswith(v_stem_lower + "."):
                lang_suffix = c_stem[len(video_path.stem) :]
                subs.append((cand, lang_suffix))
    except OSError:
        pass
    return subs


def scan_candidates(source_dirs: list[Path], min_age_sec: int) -> tuple[list[Path], list[str], list[str]]:
    videos: list[Path] = []
    skipped: list[str] = []
    errors: list[str] = []
    now_ts = time.time()

    for src in source_dirs:
        try:
            if not src.exists():
                skipped.append(f"Origen inexistente: {src}")
                continue
            entries = sorted(src.rglob("*"))
        except OSError as exc:
            errors.append(f"No se pudo recorrer {src}: {exc}")
            continue

        for item in entries:
            try:
                if not item.is_file():
                    continue
                ext = item.suffix.lower()
                if ext in IN_PROGRESS_EXTS or any(item.name.lower().endswith(e) for e in IN_PROGRESS_EXTS):
                    skipped.append(f"En curso (ignorado): {item.name}")
                    continue
                if ext not in VIDEO_EXTS:
                    continue
                if has_in_progress_sibling(item):
                    skipped.append(f"Archivo en descarga activa (ignorado): {item.name}")
                    continue
                age = now_ts - item.stat().st_mtime
                if min_age_sec > 0 and age < min_age_sec:
                    skipped.append(f"Modificado recientemente ({int(age)}s < {min_age_sec}s): {item.name}")
                    continue
                videos.append(item)
            except OSError as exc:
                errors.append(f"Error leyendo {item}: {exc}")
                continue
    return videos, skipped, errors


def run_rclone_incremental(dest_root: Path, remote: str, dry_run: bool) -> dict[str, Any]:
    rclone_bin = shutil.which("rclone")
    if not rclone_bin:
        return {"ran": False, "ok": True, "detail": "rclone no instalado (sincronización omitida)."}
    if not remote or ":" not in remote:
        return {"ran": False, "ok": True, "detail": "RCLONE_REMOTE no configurado (sincronización omitida)."}

    remote_name = remote.split(":", 1)[0] + ":"
    try:
        lr = subprocess.run(
            [rclone_bin, "listremotes"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        remotes = {line.strip() for line in (lr.stdout or "").splitlines() if line.strip()}
        if remote_name not in remotes:
            return {
                "ran": False,
                "ok": True,
                "detail": f"Remoto rclone '{remote_name}' no configurado todavía (sincronización omitida).",
            }

        cmd = [rclone_bin, "copy", str(dest_root), remote, "--update", "--transfers", "2"]
        if dry_run:
            cmd.append("--dry-run")
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        ok = res.returncode == 0
        detail = "rclone copy OK" if ok else f"rclone error (rc={res.returncode}): {(res.stderr or res.stdout).strip()[:200]}"
        return {"ran": True, "ok": ok, "dry_run": dry_run, "detail": detail}
    except Exception as exc:
        return {"ran": True, "ok": False, "detail": f"Excepción ejecutando rclone: {exc}"}


def load_state() -> dict[str, Any]:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed": [], "last_run": ""}


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    env = notify_telegram.load_env()
    parser = argparse.ArgumentParser(description="Organizador automático de biblioteca multimedia (Rama 1).")
    parser.add_argument(
        "--source",
        action="append",
        help="Carpeta(s) a vigilar (puede repetirse; por defecto DOWNLOADS_DIR de .env).",
    )
    parser.add_argument(
        "--dest",
        default="",
        help="Carpeta raíz de biblioteca destino (por defecto MEDIA_LIB_DIR de .env).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Simula sin mover archivos, sin guardar estado ni notificar.")
    parser.add_argument("--min-age-sec", type=int, default=60, help="Antigüedad mínima en segundos para evitar archivos en escritura (default: 60).")
    parser.add_argument("--no-rclone", action="store_true", help="Omitir sincronización incremental con rclone.")
    parser.add_argument("--no-notify", action="store_true", help="No enviar notificación a Telegram.")
    parser.add_argument("--json", action="store_true", help="Salida estructurada en JSON.")
    args = parser.parse_args()

    source_dirs: list[Path] = []
    if args.source:
        source_dirs = [Path(s).expanduser().resolve() for s in args.source]
    else:
        dl_env = env.get("DOWNLOADS_DIR", "").strip()
        if dl_env:
            for part in dl_env.split(";"):
                if part.strip():
                    source_dirs.append(Path(part.strip()).expanduser().resolve())
        else:
            source_dirs.append((Path.home() / "Downloads").resolve())

    dest_str = args.dest.strip() or env.get("MEDIA_LIB_DIR", "").strip() or r"D:\Media"
    dest_root = Path(dest_str).expanduser().resolve()
    rclone_remote = env.get("RCLONE_REMOTE", "").strip()

    videos, skipped, io_errors = scan_candidates(source_dirs, min_age_sec=args.min_age_sec)
    actions: list[dict[str, Any]] = []
    collisions: list[str] = []
    already_organized = 0
    planned_dests: set[Path] = set()

    for vid in videos:
        plan = classify_media(vid, dest_root, source_dirs)
        dest_file: Path = plan["dest_path"]
        try:
            vid_resolved = vid.resolve()
            dest_resolved = dest_file.resolve()
            if vid_resolved == dest_resolved:
                already_organized += 1
                continue
            if dest_file.exists() or dest_resolved in planned_dests:
                collisions.append(f"Ya existe o colisiona en destino (omitido sin sobrescribir): {dest_file}")
                continue

            subs = find_companion_subtitles(vid)
            moved_subs: list[str] = []
            if not args.dry_run:
                dest_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(vid), str(dest_file))
                for sub_path, lang_suffix in subs:
                    sub_dest = dest_file.parent / f"{plan['new_base']}{lang_suffix}{sub_path.suffix.lower()}"
                    if not sub_dest.exists():
                        shutil.move(str(sub_path), str(sub_dest))
                        moved_subs.append(sub_dest.name)
            else:
                for sub_path, lang_suffix in subs:
                    moved_subs.append(f"{plan['new_base']}{lang_suffix}{sub_path.suffix.lower()}")

            planned_dests.add(dest_resolved)
            actions.append(
                {
                    "kind": plan["kind"],
                    "title": plan["title"],
                    "source": str(vid),
                    "dest": str(dest_file),
                    "subtitles": moved_subs,
                }
            )
        except OSError as exc:
            io_errors.append(f"Error de acceso con {vid} -> {dest_file}: {exc}")

    rclone_res = (
        {"ran": False, "ok": True, "detail": "Omitido por --no-rclone."}
        if args.no_rclone
        else (
            run_rclone_incremental(dest_root, rclone_remote, dry_run=args.dry_run)
            if actions
            else {"ran": False, "ok": True, "detail": "Sin títulos nuevos; no se invoca rclone."}
        )
    )

    state = load_state()
    processed_set = set(state.get("processed", []))
    newly_notifiable = [a for a in actions if a["dest"] not in processed_set]

    log_level = "ERROR" if io_errors else "INFO"
    log_line(
        log_level,
        f"dry_run={args.dry_run} sources={[str(s) for s in source_dirs]} dest={dest_root} "
        f"processed={len(actions)} already_ok={already_organized} skipped={len(skipped)} "
        f"collisions={len(collisions)} errors={len(io_errors)} rclone={rclone_res['detail']}",
    )
    for err in io_errors:
        log_line("ERROR", err)

    notified = False
    if not args.dry_run and not args.no_notify and newly_notifiable:
        lines_tg = [f"*Biblioteca Multimedia: {len(newly_notifiable)} título(s) nuevo(s) listo(s)*"]
        for a in newly_notifiable[:12]:
            lines_tg.append(f"- [{a['kind'].upper()}] `{a['title']}`")
        if rclone_res.get("ran"):
            lines_tg.append(f"\nNube: {rclone_res['detail']}")
        notified = notify_telegram.send_telegram("\n".join(lines_tg))
        log_line("INFO" if notified else "ERROR", f"notificacion_telegram={notified}")

    if not args.dry_run and actions:
        merged = list(state.get("processed", []))
        for a in actions:
            if a["dest"] not in processed_set:
                merged.append(a["dest"])
                processed_set.add(a["dest"])
        state["processed"] = merged[-1000:]
        state["last_run"] = now_iso()
        save_state(state)

    payload = {
        "timestamp": now_iso(),
        "dry_run": args.dry_run,
        "sources": [str(s) for s in source_dirs],
        "dest": str(dest_root),
        "already_organized": already_organized,
        "actions": actions,
        "skipped": skipped,
        "collisions": collisions,
        "errors": io_errors,
        "rclone": rclone_res,
        "notified": notified,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        mode = "[DRY-RUN] " if args.dry_run else ""
        print(f"=== {mode}ORGANIZADOR MULTIMEDIA (Antigravity-Hub) ===")
        print(f"Orígenes: {', '.join(str(s) for s in source_dirs)}")
        print(f"Destino:  {dest_root}")
        print(f"Títulos {'a mover' if args.dry_run else 'movidos'}: {len(actions)} (ya ordenados: {already_organized})")
        for a in actions:
            print(f"  - [{a['kind']}] {Path(a['source']).name} -> {a['dest']}")
            if a["subtitles"]:
                print(f"      Subtítulos: {', '.join(a['subtitles'])}")
        if skipped:
            print(f"Ignorados ({len(skipped)}):")
            for s in skipped[:10]:
                print(f"  - {s}")
        if collisions:
            print(f"Colisiones omitidas ({len(collisions)}):")
            for c in collisions[:10]:
                print(f"  - {c}")
        if io_errors:
            print(f"Errores de acceso ({len(io_errors)}):")
            for e in io_errors[:10]:
                print(f"  - {e}")
        print(f"rclone:   {rclone_res['detail']}")
        print(f"Telegram: {'enviado' if notified else 'silencioso / omitido'}")

    return 0 if (rclone_res.get("ok", True) and not io_errors) else 1


if __name__ == "__main__":
    sys.exit(main())
