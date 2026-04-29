"""Config loader — merges YAML file + environment variables."""
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

load_dotenv()

_CONFIG: dict = {}

def load_config(path: str = "config/settings.yaml") -> dict:
    global _CONFIG
    with open(Path(path)) as f:
        _CONFIG = yaml.safe_load(f)
    # Overlay secrets from env
    _CONFIG.setdefault("claude", {})["api_key"] = os.getenv("ANTHROPIC_API_KEY", "")
    _CONFIG.setdefault("notifications", {})["slack_webhook_url"] = (
        os.getenv("SLACK_WEBHOOK_URL") or _CONFIG.get("notifications", {}).get("slack_webhook_url", "")
    )
    return _CONFIG

def get_config() -> dict:
    if not _CONFIG:
        load_config()
    return _CONFIG
