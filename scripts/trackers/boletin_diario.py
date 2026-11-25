#!/usr/bin/env python3
"""Boletín matutino unificado (24h) - Rama 2 Antigravity-Hub.

Combina en 1 único digest diario por Telegram:
1. Nuevos releases en GitHub de software open-source (Atom feeds).
2. Notas de parche de juegos (Steam News API + League of Legends DDragon/News).
3. Feeds RSS de estrenos/novedades de anime y series.

Deduplica usando `state/boletin_vistos.json` y registra en `logs/boletin_diario.log`.
"""

from __future__ import annotations

import argparse
import email.utils
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
SOURCES_PATH = ROOT_DIR / "state" / "boletin_fuentes.json"
STATE_PATH = ROOT_DIR / "state" / "boletin_vistos.json"
LOG_PATH = ROOT_DIR / "logs" / "boletin_diario.log"

sys.path.insert(0, str(ROOT_DIR / "scripts" / "common"))
import notify_telegram  # noqa: E402

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, application/xml, text/xml, text/html, */*",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def log_line(level: str, message: str) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(f"{now_iso()} [{level}] {message}\n")


def fetch_text(url: str, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_dt(raw: str | None) -> datetime | None:
    if not raw:
        return None
    raw = raw.strip()
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    try:
        dt = email.utils.parsedate_to_datetime(raw)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def collect_github_releases(repos: list[dict[str, str]], cutoff: datetime) -> tuple[list[dict[str, str]], list[str]]:
    items: list[dict[str, str]] = []
    errors: list[str] = []
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    for r in repos:
        name = r["name"]
        repo = r["repo"]
        url = f"https://github.com/{repo}/releases.atom"
        try:
            root = ET.fromstring(fetch_text(url))
            for entry in root.findall("atom:entry", ns)[:3]:
                title = html.unescape((entry.findtext("atom:title", default="", namespaces=ns) or "").strip())
                updated_raw = (
                    entry.findtext("atom:updated", default="", namespaces=ns)
                    or entry.findtext("atom:published", default="", namespaces=ns)
                )
                dt = parse_dt(updated_raw)
                if dt and dt < cutoff:
                    continue
                link_el = entry.find("atom:link", ns)
                href = link_el.attrib.get("href", "") if link_el is not None else ""
                entry_id = (entry.findtext("atom:id", default="", namespaces=ns) or href or f"{repo}:{title}").strip()
                items.append(
                    {
                        "id": f"gh:{entry_id}",
                        "source": name,
                        "title": title,
                        "url": href or f"https://github.com/{repo}/releases",
                        "date": dt.isoformat() if dt else "",
                    }
                )
        except Exception as exc:
            errors.append(f"GitHub {name}: {exc}")
    return items, errors


def collect_games(games: list[dict[str, Any]], cutoff: datetime, seen_ids: set[str]) -> tuple[list[dict[str, str]], list[str]]:
    items: list[dict[str, str]] = []
    errors: list[str] = []

    for g in games:
        gtype = g.get("type")
        name = g["name"]
        try:
            if gtype == "steam_news":
                appid = g["appid"]
                url = f"https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/?appid={appid}&count=5"
                data = json.loads(fetch_text(url))
                for news in data.get("appnews", {}).get("newsitems", []):
                    dt = datetime.fromtimestamp(int(news.get("date", 0)), tz=timezone.utc)
                    if dt < cutoff:
                        continue
                    gid = str(news.get("gid", ""))
                    title = html.unescape(str(news.get("title") or "").strip())
                    items.append(
                        {
                            "id": f"steam:{appid}:{gid}",
                            "source": name,
                            "title": title,
                            "url": str(news.get("url") or f"https://store.steampowered.com/news/app/{appid}"),
                            "date": dt.isoformat(),
                        }
                    )
            elif gtype == "lol_patch":
                versions = json.loads(fetch_text("https://ddragon.leagueoflegends.com/api/versions.json"))
                latest = versions[0] if versions else ""
                if latest:
                    item_id = f"lol:version:{latest}"
                    patch_url = "https://www.leagueoflegends.com/es-ar/news/tags/patch-notes/"
                    try:
                        html_txt = fetch_text("https://www.leagueoflegends.com/es-ar/news/tags/patch-notes/")
                        m_href = re.search(r'href="(/es-ar/news/game-updates/notas-de-la-version-[^"]+)"', html_txt, re.I)
                        if m_href:
                            patch_url = "https://www.leagueoflegends.com" + m_href.group(1)
                    except Exception:
                        pass
                    # Solo reportar nueva versión si aún no fue vista
                    if item_id not in seen_ids:
                        items.append(
                            {
                                "id": item_id,
                                "source": name,
                                "title": f"Versión activa {latest} (Notas del parche)",
                                "url": patch_url,
                                "date": now_utc().isoformat(),
                            }
                        )
        except Exception as exc:
            errors.append(f"Juego {name}: {exc}")
    return items, errors


def collect_rss_feeds(feeds: list[dict[str, str]], cutoff: datetime) -> tuple[list[dict[str, str]], list[str]]:
    items: list[dict[str, str]] = []
    errors: list[str] = []

    for f in feeds:
        name = f["name"]
        try:
            root = ET.fromstring(fetch_text(f["url"]))
            # Soporta RSS 2.0 (<item>) y Atom (<entry>)
            rss_items = root.findall(".//item")
            if rss_items:
                for el in rss_items[:12]:
                    title = html.unescape(re.sub(r"<[^>]+>", "", el.findtext("title") or "").strip())
                    link = (el.findtext("link") or "").strip()
                    pub = el.findtext("pubDate") or el.findtext("{http://purl.org/dc/elements/1.1/}date")
                    dt = parse_dt(pub)
                    if dt and dt < cutoff:
                        continue
                    guid = (el.findtext("guid") or link or title).strip()
                    items.append(
                        {
                            "id": f"rss:{guid}",
                            "source": name,
                            "title": title,
                            "url": link,
                            "date": dt.isoformat() if dt else "",
                        }
                    )
            else:
                ns = {"atom": "http://www.w3.org/2005/Atom"}
                for el in root.findall("atom:entry", ns)[:12]:
                    title = html.unescape((el.findtext("atom:title", default="", namespaces=ns) or "").strip())
                    dt = parse_dt(el.findtext("atom:updated", default="", namespaces=ns) or el.findtext("atom:published", default="", namespaces=ns))
                    if dt and dt < cutoff:
                        continue
                    link_el = el.find("atom:link", ns)
                    href = link_el.attrib.get("href", "") if link_el is not None else ""
                    eid = (el.findtext("atom:id", default="", namespaces=ns) or href or title).strip()
                    items.append(
                        {
                            "id": f"rss:{eid}",
                            "source": name,
                            "title": title,
                            "url": href,
                            "date": dt.isoformat() if dt else "",
                        }
                    )
        except Exception as exc:
            errors.append(f"RSS {name}: {exc}")
    return items, errors


def load_json(path: Path, default: Any) -> Any:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            pass
    return default


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Boletín matutino unificado (Rama 2 - Antigravity-Hub).")
    parser.add_argument("--hours", type=int, default=0, help="Ventana en horas hacia atrás (por defecto usa boletin_fuentes.json).")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin guardar estado ni enviar Telegram.")
    parser.add_argument("--json", action="store_true", help="Imprimir resultado en JSON.")
    args = parser.parse_args()

    cfg = load_json(SOURCES_PATH, {})
    state = load_json(STATE_PATH, {"seen_ids": [], "last_run": ""})
    seen_ids = set(state.get("seen_ids", []))

    hours = args.hours if args.hours > 0 else int(cfg.get("horas_ventana", 24))
    max_per_sec = int(cfg.get("max_items_por_seccion", 5))
    cutoff = now_utc() - timedelta(hours=hours)

    gh_items, err_gh = collect_github_releases(cfg.get("github_releases", []), cutoff)
    game_items, err_gm = collect_games(cfg.get("juegos", []), cutoff, seen_ids)
    rss_items, err_rss = collect_rss_feeds(cfg.get("anime_y_series", []), cutoff)

    def filter_new(items: list[dict[str, str]]) -> list[dict[str, str]]:
        # Intercalar por fuente (round-robin) para que una sola fuente no sature la sección
        buckets: dict[str, list[dict[str, str]]] = {}
        local_seen: set[str] = set()
        for it in items:
            if it["id"] in seen_ids or it["id"] in local_seen:
                continue
            local_seen.add(it["id"])
            buckets.setdefault(it["source"], []).append(it)

        out: list[dict[str, str]] = []
        source_lists = list(buckets.values())
        idx = 0
        while len(out) < max_per_sec and source_lists:
            progressed = False
            for lst in source_lists:
                if idx < len(lst):
                    out.append(lst[idx])
                    progressed = True
                    if len(out) >= max_per_sec:
                        break
            if not progressed:
                break
            idx += 1
        return out

    new_gh = filter_new(gh_items)
    new_gm = filter_new(game_items)
    new_rss = filter_new(rss_items)
    all_new = new_gh + new_gm + new_rss
    errors = err_gh + err_gm + err_rss

    log_line(
        "INFO",
        f"hours={hours} gh={len(new_gh)} games={len(new_gm)} anime_series={len(new_rss)} "
        f"errors={len(errors)} dry_run={args.dry_run}",
    )
    for e in errors:
        log_line("WARN", f"source_error: {e}")

    notified = False
    if all_new and not args.dry_run:
        sections: list[str] = [f"<b>Boletín Matutino ({datetime.now().strftime('%d/%m')}) — Últimas {hours}h</b>"]
        if new_gh:
            sections.append("\n<b>Software Open-Source (Releases)</b>")
            for it in new_gh:
                sections.append(f"• {html.escape(it['source'])}: <code>{html.escape(it['title'])}</code> — {html.escape(it['url'])}")
        if new_gm:
            sections.append("\n<b>Juegos (Parches / Noticias)</b>")
            for it in new_gm:
                sections.append(f"• {html.escape(it['source'])}: {html.escape(it['title'][:90])} — {html.escape(it['url'])}")
        if new_rss:
            sections.append("\n<b>Anime &amp; Series</b>")
            for it in new_rss:
                sections.append(f"• [{html.escape(it['source'])}] {html.escape(it['title'][:90])} — {html.escape(it['url'])}")
        notified = notify_telegram.send_telegram("\n".join(sections), parse_mode="HTML")
        log_line("INFO" if notified else "ERROR", f"notificacion_telegram={notified}")

    if not args.dry_run:
        merged = list(state.get("seen_ids", []))
        for it in (gh_items + game_items + rss_items):
            if it["id"] not in seen_ids:
                merged.append(it["id"])
                seen_ids.add(it["id"])
        state["seen_ids"] = merged[-3000:]
        state["last_run"] = now_iso()
        save_json(STATE_PATH, state)

    payload = {
        "timestamp": now_iso(),
        "hours": hours,
        "dry_run": args.dry_run,
        "github_releases": new_gh,
        "games": new_gm,
        "anime_series": new_rss,
        "errors": errors,
        "notified": notified,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        mode = "[DRY-RUN] " if args.dry_run else ""
        print(f"=== {mode}BOLETÍN MATUTINO (últimas {hours}h) ===")
        for label, grp in (("GitHub Releases", new_gh), ("Juegos", new_gm), ("Anime y Series", new_rss)):
            print(f"\n[{label}] ({len(grp)})")
            for it in grp:
                print(f"  - {it['source']}: {it['title']} ({it['url']})")
        if errors:
            print("\nAvisos de fuentes:", "; ".join(errors))
        print(f"\nTelegram: {'enviado' if notified else 'silencioso (sin novedades)'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
