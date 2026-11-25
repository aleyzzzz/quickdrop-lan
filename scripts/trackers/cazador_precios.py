#!/usr/bin/env python3
"""Cazador de precios (vuelos y productos/hardware) - Rama 2 Antigravity-Hub.

Lee objetivos desde `state/watchlist.json`, deduplica contra `state/precios_vistos.json`,
registra en `logs/cazador_precios.log` y avisa por `scripts/common/notify_telegram.py`
ÚNICAMENTE si el precio está por debajo del umbral configurado Y bajó respecto al
último aviso guardado para ese ítem.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
WATCHLIST_PATH = ROOT_DIR / "state" / "watchlist.json"
STATE_PATH = ROOT_DIR / "state" / "precios_vistos.json"
LOG_PATH = ROOT_DIR / "logs" / "cazador_precios.log"

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


def parse_number(raw: str) -> float | None:
    s = raw.strip().replace("\xa0", "").replace(" ", "")
    if not s:
        return None
    # Formato argentino/latino: 150.000,50 o 150.000
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "." in s:
        parts = s.split(".")
        if len(parts) > 2 or (len(parts) == 2 and len(parts[1]) == 3 and len(parts[0]) >= 1):
            s = s.replace(".", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def extract_flight_price(text: str, currency: str) -> float | None:
    clean = html.unescape(re.sub(r"<[^>]+>", " ", text))
    cur = currency.upper()
    if cur == "USD":
        patterns = [
            r"(?:U\$D|U\$S|US\$|USD)\s*([0-9][0-9.,]*)",
            r"([0-9][0-9.,]*)\s*(?:USD|dólares|dolares)",
        ]
    elif cur == "EUR":
        patterns = [
            r"(?:EUR|€)\s*([0-9][0-9.,]*)",
            r"([0-9][0-9.,]*)\s*(?:EUR|euros)",
        ]
    else:
        patterns = [
            r"(?:ARS|\$)\s*([0-9][0-9.,]*)",
        ]
    candidates: list[float] = []
    for pat in patterns:
        for m in re.finditer(pat, clean, re.IGNORECASE):
            val = parse_number(m.group(1))
            if val is not None and 50 <= val <= 10_000_000:
                candidates.append(val)
    return min(candidates) if candidates else None


def check_rss_flight(item: dict[str, Any]) -> dict[str, Any]:
    must_groups = item.get("must_match_all") or []
    exclude = [k.lower() for k in item.get("exclude_keywords", [])]
    currency = item.get("currency", "USD")
    best: dict[str, Any] | None = None
    errors: list[str] = []

    for url in item.get("urls", []):
        try:
            xml_text = fetch_text(url)
            root = ET.fromstring(xml_text)
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue

        for el in root.findall(".//item"):
            title = (el.findtext("title") or "").strip()
            link = (el.findtext("link") or "").strip()
            desc = (el.findtext("description") or "").strip()
            blob = f"{title} {desc}".lower()
            if exclude and any(ex in blob for ex in exclude):
                continue
            if must_groups and not all(any(kw.lower() in blob for kw in grp) for grp in must_groups):
                continue
            price = extract_flight_price(f"{title} {desc}", currency)
            if price is None:
                continue
            if best is None or price < best["price"]:
                best = {
                    "ok": True,
                    "price": price,
                    "currency": currency,
                    "title": title,
                    "url": link or url,
                }

    if best:
        return best
    if errors and len(errors) == len(item.get("urls", [])):
        return {"ok": False, "error": "; ".join(errors)}
    return {"ok": True, "price": None, "currency": currency, "title": "Sin ofertas que coincidan en el feed", "url": ""}


def check_compragamer(item: dict[str, Any], catalog_cache: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    url = item.get("url", "https://static.compragamer.com/productos")
    if url not in catalog_cache:
        catalog_cache[url] = json.loads(fetch_text(url, timeout=20))
    products = catalog_cache[url]

    req_kws = [k.lower() for k in item.get("keywords", [])]
    any_kws = [k.lower() for k in item.get("any_keywords", [])]
    exc_kws = [k.lower() for k in item.get("exclude_keywords", [])]

    best_prod: dict[str, Any] | None = None
    best_price: float | None = None

    for prod in products:
        if not prod.get("vendible", True):
            continue
        stock = prod.get("stock")
        if stock is not None and float(stock) <= 0:
            continue
        name = str(prod.get("nombre") or "")
        low = name.lower()
        if not all(k in low for k in req_kws):
            continue
        if any_kws and not any(k in low for k in any_kws):
            continue
        if any(k in low for k in exc_kws):
            continue
        raw_price = prod.get("precioEspecial") or prod.get("precioLista")
        if raw_price is None:
            continue
        price = float(raw_price)
        if price <= 0:
            continue
        if best_price is None or price < best_price:
            best_price = price
            best_prod = prod

    if best_prod is None or best_price is None:
        return {"ok": True, "price": None, "currency": "ARS", "title": "Sin stock o sin coincidencias", "url": "https://compragamer.com"}

    prod_id = best_prod.get("id_producto")
    return {
        "ok": True,
        "price": best_price,
        "currency": "ARS",
        "title": str(best_prod.get("nombre", "")).strip(),
        "url": f"https://compragamer.com/producto/{prod_id}" if prod_id else "https://compragamer.com",
    }


def check_steam_app(item: dict[str, Any]) -> dict[str, Any]:
    appid = str(item["appid"])
    cc = item.get("cc", "ar")
    url = f"https://store.steampowered.com/api/appdetails?appids={appid}&cc={cc}"
    data = json.loads(fetch_text(url))
    entry = data.get(appid, {})
    if not entry.get("success"):
        return {"ok": False, "error": f"Steam appid {appid} sin datos"}
    app_data = entry.get("data", {})
    po = app_data.get("price_overview")
    if not po:
        return {"ok": True, "price": None, "currency": cc.upper(), "title": app_data.get("name", appid), "url": f"https://store.steampowered.com/app/{appid}/"}
    return {
        "ok": True,
        "price": round(float(po["final"]) / 100.0, 2),
        "currency": po.get("currency", "USD"),
        "title": app_data.get("name", appid),
        "url": f"https://store.steampowered.com/app/{appid}/",
    }


def extract_json_path(data: Any, path: str) -> Any:
    cur = data
    for part in path.split("."):
        if isinstance(cur, list) and part.isdigit():
            cur = cur[int(part)]
        elif isinstance(cur, dict):
            cur = cur[part]
        else:
            raise KeyError(part)
    return cur


def check_json_api(item: dict[str, Any]) -> dict[str, Any]:
    url = item["url"]
    data = json.loads(fetch_text(url))
    raw_val = extract_json_path(data, item["json_path"])
    price = float(raw_val) if isinstance(raw_val, (int, float)) else parse_number(str(raw_val))
    return {
        "ok": True,
        "price": price,
        "currency": item.get("currency", "ARS"),
        "title": item.get("name", url),
        "url": item.get("link_url") or url,
    }


def _find_price_in_jsonld(obj: Any) -> float | None:
    if isinstance(obj, list):
        for el in obj:
            found = _find_price_in_jsonld(el)
            if found is not None:
                return found
    elif isinstance(obj, dict):
        if "price" in obj and obj["price"] not in (None, ""):
            val = obj["price"]
            return float(val) if isinstance(val, (int, float)) else parse_number(str(val))
        for k in ("offers", "lowPrice"):
            if k in obj:
                found = _find_price_in_jsonld(obj[k])
                if found is not None:
                    return found
        for v in obj.values():
            if isinstance(v, (dict, list)):
                found = _find_price_in_jsonld(v)
                if found is not None:
                    return found
    return None


def check_html_price(item: dict[str, Any]) -> dict[str, Any]:
    url = item["url"]
    try:
        page = fetch_text(url)
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "needs_browser": exc.code in (403, 429, 503),
            "error": f"HTTP {exc.code} (si requiere JS/anti-bot, usar /browser)",
        }

    # 1) Regex personalizado si se configuró
    if item.get("regex"):
        m = re.search(item["regex"], page, re.IGNORECASE | re.DOTALL)
        if m:
            price = parse_number(m.group(1))
            if price is not None:
                return {"ok": True, "price": price, "currency": item.get("currency", "ARS"), "title": item.get("name", url), "url": url}

    # 2) JSON-LD schema.org
    for block in re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.I | re.S):
        try:
            parsed = json.loads(block.strip())
            price = _find_price_in_jsonld(parsed)
            if price is not None:
                return {"ok": True, "price": price, "currency": item.get("currency", "ARS"), "title": item.get("name", url), "url": url}
        except Exception:
            continue

    # 3) Meta tags / microdata
    meta_patterns = [
        r'<meta[^>]+property=["\'](?:product:price:amount|og:price:amount)["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)["\']',
    ]
    for pat in meta_patterns:
        m = re.search(pat, page, re.I)
        if m:
            price = parse_number(m.group(1))
            if price is not None:
                return {"ok": True, "price": price, "currency": item.get("currency", "ARS"), "title": item.get("name", url), "url": url}

    return {
        "ok": False,
        "needs_browser": True,
        "error": "No se encontró precio en HTML estático (página probablemente JS; usar /browser si hace falta)",
    }


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


def format_price(price: float | None, currency: str) -> str:
    if price is None:
        return "N/D"
    if float(price).is_integer():
        return f"{currency} {int(price):,}".replace(",", ".")
    return f"{currency} {price:,.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Cazador de precios de vuelos y hardware (Rama 2).")
    parser.add_argument("--dry-run", action="store_true", help="Simular sin actualizar state/ ni enviar alertas por Telegram.")
    parser.add_argument("--json", action="store_true", help="Imprimir resultado en formato JSON.")
    args = parser.parse_args()

    watchlist = load_json(WATCHLIST_PATH, {"items": []})
    state = load_json(STATE_PATH, {"items": {}, "last_run": ""})
    seen_items: dict[str, Any] = state.setdefault("items", {})
    catalog_cache: dict[str, list[dict[str, Any]]] = {}

    results: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []

    for item in watchlist.get("items", []):
        if not item.get("enabled", True):
            continue
        item_id = str(item["id"])
        kind = item.get("type", "html_price")
        max_price = float(item["max_price"])

        try:
            if kind == "rss_flight":
                res = check_rss_flight(item)
            elif kind == "compragamer_search":
                res = check_compragamer(item, catalog_cache)
            elif kind == "steam_app":
                res = check_steam_app(item)
            elif kind == "json_api":
                res = check_json_api(item)
            elif kind == "html_price":
                res = check_html_price(item)
            else:
                res = {"ok": False, "error": f"Tipo no soportado: {kind}"}
        except Exception as exc:
            res = {"ok": False, "error": str(exc)}

        prev = seen_items.get(item_id, {})
        last_alert_price = prev.get("last_alert_price")
        current_price = res.get("price")

        should_alert = False
        reason = "Sin precio disponible"
        if not res.get("ok"):
            reason = f"Error: {res.get('error')}"
        elif current_price is None:
            reason = res.get("title") or "Sin coincidencias"
        elif current_price > max_price:
            reason = f"Sobre umbral ({format_price(current_price, res['currency'])} > {format_price(max_price, item.get('currency', 'ARS'))})"
        elif last_alert_price is not None and current_price >= float(last_alert_price):
            reason = (
                f"Bajo umbral pero no bajó respecto al último aviso "
                f"({format_price(current_price, res['currency'])} >= {format_price(float(last_alert_price), res['currency'])})"
            )
        else:
            should_alert = True
            reason = "BAJÓ bajo el umbral y es menor al último aviso"

        entry_summary = {
            "id": item_id,
            "name": item.get("name", item_id),
            "type": kind,
            "max_price": max_price,
            "current_price": current_price,
            "last_alert_price": last_alert_price,
            "currency": res.get("currency", item.get("currency", "ARS")),
            "matched_title": res.get("title", ""),
            "url": res.get("url", ""),
            "should_alert": should_alert,
            "reason": reason,
            "needs_browser": bool(res.get("needs_browser", False)),
        }
        results.append(entry_summary)
        if should_alert:
            alerts.append(entry_summary)

        if not args.dry_run and res.get("ok"):
            prev["last_checked"] = now_iso()
            prev["last_seen_price"] = current_price
            prev["last_title"] = res.get("title", "")
            seen_items[item_id] = prev

    log_line(
        "INFO",
        f"checked={len(results)} alerts={len(alerts)} dry_run={args.dry_run} "
        + " | ".join(f"{r['id']}:{r['current_price']}({r['reason']})" for r in results),
    )

    notified = False
    if alerts and not args.dry_run:
        lines = [f"<b>Cazador de Precios — {len(alerts)} baja(s) detectada(s)</b>"]
        for a in alerts:
            prev_txt = (
                f" (antes {html.escape(format_price(float(a['last_alert_price']), a['currency']))})"
                if a["last_alert_price"] is not None
                else ""
            )
            lines.append(
                f"\n• <b>{html.escape(a['name'])}</b>\n"
                f"  Precio: <b>{html.escape(format_price(a['current_price'], a['currency']))}</b>{prev_txt} "
                f"(tope: {html.escape(format_price(a['max_price'], a['currency']))})\n"
                f"  Detalle: {html.escape(a['matched_title'][:110])}\n"
                f"  {html.escape(a['url'])}"
            )
        notified = notify_telegram.send_telegram("\n".join(lines), parse_mode="HTML")
        log_line("INFO" if notified else "ERROR", f"notificacion_telegram={notified}")
        if notified:
            for a in alerts:
                seen_items[a["id"]]["last_alert_price"] = a["current_price"]
                seen_items[a["id"]]["last_alert_at"] = now_iso()

    if not args.dry_run:
        state["last_run"] = now_iso()
        save_json(STATE_PATH, state)

    if args.json:
        print(json.dumps({"timestamp": now_iso(), "dry_run": args.dry_run, "notified": notified, "results": results}, indent=2, ensure_ascii=False))
    else:
        mode = "[DRY-RUN] " if args.dry_run else ""
        print(f"=== {mode}CAZADOR DE PRECIOS (Antigravity-Hub) ===")
        for r in results:
            print(f"- {r['name']}: {format_price(r['current_price'], r['currency'])} | {r['reason']}")
            if r["matched_title"]:
                print(f"    Título: {r['matched_title'][:100]}")
            if r["url"]:
                print(f"    URL:    {r['url']}")
        print(f"Telegram: {'enviado' if notified else 'silencioso (sin bajas nuevas)'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
