#!/usr/bin/env python3
"""Radar diario de búsquedas laborales - Rama 2 Antigravity-Hub.

Recorre fuentes abiertas/RSS/JSON/portales configuradas en `state/filtros_empleo.json`,
filtra puestos junior en informática/soporte u operativos en Zona Norte / Pilar / AMBA
o remoto, prioriza horarios compatibles con cursada nocturna (libre desde las 18:00),
descarta duplicados vía `state/vacantes_vistas.json` y envía 1 resumen diario por Telegram.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
FILTERS_PATH = ROOT_DIR / "state" / "filtros_empleo.json"
STATE_PATH = ROOT_DIR / "state" / "vacantes_vistas.json"
LOG_PATH = ROOT_DIR / "logs" / "radar_laboral.log"

sys.path.insert(0, str(ROOT_DIR / "scripts" / "common"))
import notify_telegram  # noqa: E402

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, application/xml, text/xml, text/html, */*",
    "Accept-Language": "es-AR,es;q=0.9,en;q=0.8",
}


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


def clean_html(raw: str) -> str:
    txt = re.sub(r"<[^>]+>", " ", raw or "")
    txt = html.unescape(txt)
    return re.sub(r"\s+", " ", txt).strip()


def canonical_url(url: str) -> str:
    return url.split("#", 1)[0].strip()


def job_fingerprint(title: str, company: str, url: str) -> str:
    base = f"{title.lower().strip()}|{company.lower().strip()}|{canonical_url(url)}"
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


def fetch_computrabajo(src: dict[str, Any]) -> list[dict[str, Any]]:
    page = fetch_text(src["url"])
    jobs: list[dict[str, Any]] = []
    articles = re.findall(r"<article\b[^>]*>(.*?)</article>", page, re.I | re.S)
    for art in articles:
        m_link = re.search(
            r'<a[^>]*class="[^"]*js-o-link[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            art,
            re.I | re.S,
        )
        if not m_link:
            continue
        href, raw_title = m_link.group(1), m_link.group(2)
        title = clean_html(raw_title)
        full_url = "https://ar.computrabajo.com" + canonical_url(href) if href.startswith("/") else canonical_url(href)

        m_comp = re.search(r'<a[^>]*offer-company[^>]*>(.*?)</a>', art, re.I | re.S)
        if not m_comp:
            m_comp = re.search(r'<a[^>]*class="[^"]*fc_base[^"]*t_ellipsis[^"]*"[^>]*>(.*?)</a>', art, re.I | re.S)
        company = clean_html(m_comp.group(1)) if m_comp else ""
        if not company or company.lower() in ("importante empresa", "empresa confidencial") or company.lower() == title.lower():
            company = "Empresa en Computrabajo"

        # Extraer ubicación real desde URL (`...-en-pilar-...`)
        location = src.get("default_location", "Buenos Aires")
        m_loc_url = re.search(r"-en-([a-z0-9-]+)-[0-9A-F]{16,}", full_url, re.I)
        if m_loc_url:
            location = m_loc_url.group(1).replace("-", " ").title()

        snippet = clean_html(art)

        jobs.append(
            {
                "source": src["name"],
                "title": title,
                "company": company,
                "location": location,
                "remote": "remoto" in snippet.lower() or "híbrido" in snippet.lower(),
                "text": snippet,
                "url": full_url,
            }
        )
    return jobs


def fetch_getonbrd(src: dict[str, Any]) -> list[dict[str, Any]]:
    data = json.loads(fetch_text(src["url"]))
    jobs: list[dict[str, Any]] = []
    for entry in data.get("data", []):
        attr = entry.get("attributes", {})
        comp_obj = attr.get("company") or {}
        comp = ((comp_obj.get("data") or {}).get("attributes") or {}).get("name") or ""
        if not comp:
            comp_id = (comp_obj.get("data") or {}).get("id")
            comp = str(comp_id).replace("-", " ").title() if comp_id else "Empresa en Get on Board"
        raw_countries = attr.get("countries")
        if isinstance(raw_countries, list):
            countries = ", ".join(str(c) for c in raw_countries)
        elif isinstance(raw_countries, dict):
            countries = ", ".join(str(c.get("id") or "") for c in raw_countries.get("data", []) if isinstance(c, dict))
        else:
            countries = ""
        raw_cities = attr.get("location_cities")
        cities = ", ".join(str(c) for c in raw_cities) if isinstance(raw_cities, list) else ""
        loc = cities or countries or ("Remoto" if attr.get("remote") else "Latam")
        desc = clean_html(
            " ".join(
                str(attr.get(k) or "")
                for k in ("description_headline", "description", "functions", "desirable")
            )
        )
        url = ((entry.get("links") or {}).get("public_url")) or f"https://www.getonbrd.com/jobs/{entry.get('id')}"
        jobs.append(
            {
                "source": src["name"],
                "title": str(attr.get("title") or "").strip(),
                "company": str(comp).strip(),
                "location": loc,
                "remote": bool(attr.get("remote")),
                "text": f"{loc} {attr.get('modality', '')} {desc}",
                "url": canonical_url(url),
            }
        )
    return jobs


def fetch_remotive(src: dict[str, Any]) -> list[dict[str, Any]]:
    data = json.loads(fetch_text(src["url"]))
    jobs: list[dict[str, Any]] = []
    for j in data.get("jobs", []):
        loc = str(j.get("candidate_required_location") or "Worldwide")
        jobs.append(
            {
                "source": src["name"],
                "title": str(j.get("title") or "").strip(),
                "company": str(j.get("company_name") or "").strip(),
                "location": loc,
                "remote": True,
                "text": f"{loc} {j.get('job_type', '')} {clean_html(j.get('description', ''))[:600]}",
                "url": canonical_url(str(j.get("url") or "")),
            }
        )
    return jobs


def fetch_jobicy(src: dict[str, Any]) -> list[dict[str, Any]]:
    data = json.loads(fetch_text(src["url"]))
    jobs: list[dict[str, Any]] = []
    for j in data.get("jobs", []):
        loc = str(j.get("jobGeo") or "Anywhere")
        jobs.append(
            {
                "source": src["name"],
                "title": html.unescape(str(j.get("jobTitle") or "").strip()),
                "company": html.unescape(str(j.get("companyName") or "").strip()),
                "location": loc,
                "remote": True,
                "text": f"{loc} {j.get('jobLevel', '')} {clean_html(j.get('jobExcerpt', ''))}",
                "url": canonical_url(str(j.get("url") or "")),
            }
        )
    return jobs


def fetch_rss(src: dict[str, Any]) -> list[dict[str, Any]]:
    root = ET.fromstring(fetch_text(src["url"]))
    jobs: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = clean_html(item.findtext("title") or "")
        link = canonical_url(item.findtext("link") or "")
        desc = clean_html(item.findtext("description") or "")
        jobs.append(
            {
                "source": src["name"],
                "title": title,
                "company": src.get("default_company", "Portal RSS"),
                "location": src.get("default_location", "Remoto / Argentina"),
                "remote": "remoto" in desc.lower() or "remote" in desc.lower(),
                "text": desc[:700],
                "url": link,
            }
        )
    return jobs


def evaluate_job(job: dict[str, Any], cfg: dict[str, Any]) -> tuple[bool, int, str]:
    title_low = job["title"].lower()
    url_norm = job["url"].lower().replace("-", " ")
    full_low = f"{job['title']} {job['location']} {job['text']} {url_norm}".lower()

    excludes = [w.lower() for w in cfg.get("palabras_clave_excluir", [])]
    for ex in excludes:
        if re.search(rf"(?<!\w){re.escape(ex)}(?!\w)", f"{title_low} {url_norm}"):
            return False, 0, ""

    bad_sched = [w.lower() for w in cfg.get("horarios_incompatibles_cursada_18", [])]
    if any(bs in full_low for bs in bad_sched):
        return False, 0, ""

    includes = [w.lower() for w in cfg.get("palabras_clave_incluir", [])]
    matched_role = [
        kw for kw in includes
        if re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", f"{title_low} {full_low[:260]}")
    ]
    if not matched_role:
        return False, 0, ""

    # Evitar que "técnico" suelto capture oficios no IT (refrigeración, electromecánica, construcción)
    it_anchors = ("soporte", "it", "informatica", "informática", "sistemas", "help desk", "helpdesk", "mesa de ayuda", "field support", "redes", "infraestructura", "microinformatica", "microinformática", "sysadmin", "software", "computacion", "computación")
    if set(matched_role).issubset({"tecnico", "técnico", "jr", "junior", "operativo"}) and not any(
        re.search(rf"(?<!\w){re.escape(a)}(?!\w)", full_low) for a in it_anchors
    ):
        return False, 0, ""

    locs = [w.lower() for w in cfg.get("ubicaciones_prioritarias", [])]
    loc_text = f"{job['location']} {url_norm}".lower()
    matched_loc = [loc for loc in locs if loc in loc_text]
    if not matched_loc and not job.get("remote"):
        return False, 0, ""

    score = len(matched_role) * 2 + (3 if matched_loc else 0)
    if any(z in full_low for z in ("pilar", "zona norte", "escobar", "tigre", "san isidro", "garin", "garín", "tortuguitas")):
        score += 5
    elif "argentina" in full_low or "buenos aires" in full_low:
        score += 3

    good_sched = [w.lower() for w in cfg.get("horarios_compatibles", [])]
    matched_sched = [gs for gs in good_sched if gs in full_low]
    if matched_sched:
        score += 2

    reasons: list[str] = []
    reasons.append("rol: " + ", ".join(matched_role[:2]))
    if matched_loc:
        reasons.append("zona: " + matched_loc[0])
    elif job.get("remote"):
        reasons.append("zona: remoto")
    if matched_sched:
        reasons.append("compatible <18h (" + matched_sched[0] + ")")
    else:
        reasons.append("sin conflicto horario visible (<18h)")

    return True, score, " | ".join(reasons)


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
    parser = argparse.ArgumentParser(description="Radar diario de búsquedas laborales (Rama 2).")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin guardar vacantes vistas ni enviar Telegram.")
    parser.add_argument("--json", action="store_true", help="Salida estructurada en JSON.")
    args = parser.parse_args()

    cfg = load_json(FILTERS_PATH, {"fuentes": []})
    state = load_json(STATE_PATH, {"seen_ids": [], "seen_urls": [], "last_run": ""})
    seen_ids = set(state.get("seen_ids", []))
    seen_urls = set(state.get("seen_urls", []))

    raw_jobs: list[dict[str, Any]] = []
    source_errors: list[str] = []

    for src in cfg.get("fuentes", []):
        if not src.get("enabled", True):
            continue
        stype = src.get("type", "")
        try:
            if stype == "computrabajo":
                raw_jobs.extend(fetch_computrabajo(src))
            elif stype == "getonbrd":
                raw_jobs.extend(fetch_getonbrd(src))
            elif stype == "remotive":
                raw_jobs.extend(fetch_remotive(src))
            elif stype == "jobicy":
                raw_jobs.extend(fetch_jobicy(src))
            elif stype == "rss":
                raw_jobs.extend(fetch_rss(src))
        except Exception as exc:
            source_errors.append(f"{src.get('name')}: {exc}")

    # Evaluar y deduplicar dentro de la corrida + contra historial
    dedup_run: dict[str, dict[str, Any]] = {}
    for job in raw_jobs:
        if not job.get("title") or not job.get("url"):
            continue
        ok, score, reason = evaluate_job(job, cfg)
        if not ok:
            continue
        fp = job_fingerprint(job["title"], job["company"], job["url"])
        url_key = canonical_url(job["url"])
        if fp in seen_ids or url_key in seen_urls or fp in dedup_run:
            continue
        job["id"] = fp
        job["score"] = score
        job["reason"] = reason
        dedup_run[fp] = job

    max_items = int(cfg.get("max_resultados_diarios", 12))
    matched = sorted(dedup_run.values(), key=lambda j: j["score"], reverse=True)[:max_items]

    log_line(
        "INFO",
        f"raw={len(raw_jobs)} new_matches={len(matched)} errors={len(source_errors)} dry_run={args.dry_run}",
    )
    for err in source_errors:
        log_line("WARN", f"source_error: {err}")

    notified = False
    if matched and not args.dry_run:
        lines = [f"<b>Radar Laboral Diario — {len(matched)} vacante(s) nueva(s)</b>"]
        for idx, j in enumerate(matched, 1):
            lines.append(
                f"\n{idx}. <b>{html.escape(j['title'])}</b>\n"
                f"   Empresa: {html.escape(j['company'])} ({html.escape(j['location'])})\n"
                f"   Match: <i>{html.escape(j['reason'])}</i>\n"
                f"   {html.escape(j['url'])}"
            )
        notified = notify_telegram.send_telegram("\n".join(lines), parse_mode="HTML")
        log_line("INFO" if notified else "ERROR", f"notificacion_telegram={notified}")

    if not args.dry_run:
        new_ids = list(state.get("seen_ids", []))
        new_urls = list(state.get("seen_urls", []))
        for j in matched:
            if j["id"] not in seen_ids:
                new_ids.append(j["id"])
            if j["url"] not in seen_urls:
                new_urls.append(j["url"])
        state["seen_ids"] = new_ids[-2000:]
        state["seen_urls"] = new_urls[-2000:]
        state["last_run"] = now_iso()
        save_json(STATE_PATH, state)

    if args.json:
        print(json.dumps({"timestamp": now_iso(), "dry_run": args.dry_run, "raw_count": len(raw_jobs), "matches": matched, "errors": source_errors, "notified": notified}, indent=2, ensure_ascii=False))
    else:
        mode = "[DRY-RUN] " if args.dry_run else ""
        print(f"=== {mode}RADAR LABORAL DIARIO (Antigravity-Hub) ===")
        print(f"Ofertas revisadas: {len(raw_jobs)} | Nuevos matches: {len(matched)}")
        for idx, j in enumerate(matched, 1):
            print(f"{idx}. {j['title']} — {j['company']} [{j['location']}]")
            print(f"   Motivo: {j['reason']}")
            print(f"   Link:   {j['url']}")
        if source_errors:
            print("Avisos de fuentes:", "; ".join(source_errors))
        print(f"Telegram: {'enviado' if notified else 'silencioso (sin vacantes nuevas)'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
