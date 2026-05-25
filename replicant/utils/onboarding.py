"""First-run onboarding wizard and config file management."""
from __future__ import annotations
import json
from pathlib import Path

from rich.console import Console

_CONFIG_PATH = Path.home() / ".replicant" / "config.json"
_con = Console()


def load_config() -> dict:
    """Load ~/.replicant/config.json. Returns {} if missing or malformed."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(_CONFIG_PATH.read_text())
    except Exception:
        return {}


def save_config(cfg: dict) -> None:
    """Write cfg to ~/.replicant/config.json atomically."""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_PATH.write_text(json.dumps(cfg, indent=2))
