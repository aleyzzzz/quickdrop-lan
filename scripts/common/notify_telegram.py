import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


def load_env() -> dict[str, str]:
    env_path = Path(__file__).resolve().parents[2] / ".env"
    env_vars = dict(os.environ)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env_vars.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env_vars


def send_telegram(message: str, parse_mode: str = "Markdown") -> bool:
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = env.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id or "pegar_tu_" in token:
        print("Error: configurá TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env", file=sys.stderr)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps(
        {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        print(f"Error HTTP de Telegram ({e.code}): {body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Error de conexión con Telegram: {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    msg = " ".join(sys.argv[1:]).strip() or "Antigravity-Hub: conexión de prueba OK"
    ok = send_telegram(msg)
    sys.exit(0 if ok else 1)
