"""MUON Protocol — Telegram notification to owner."""

import json
import urllib.request
import urllib.error
from pathlib import Path


def _load_telegram_config() -> tuple[str, str]:
    """Load bot token and owner ID from MUSEON .env."""
    env_path = Path.home() / "MUSEON" / ".env"
    token, owner_id = "", ""
    if env_path.exists():
        for line in env_path.read_text().split("\n"):
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                token = line.split("=", 1)[1].strip()
            if line.startswith("TELEGRAM_OWNER_ID="):
                owner_id = line.split("=", 1)[1].strip()
    return token, owner_id


def send_telegram(message: str) -> bool:
    """Send a Telegram message to the owner. Returns True if sent."""
    token, owner_id = _load_telegram_config()
    if not token or not owner_id:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": owner_id,
        "text": message,
        "parse_mode": "HTML",
    }).encode()

    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except (urllib.error.URLError, urllib.error.HTTPError):
        return False
