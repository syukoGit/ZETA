import json
import os
from pathlib import Path
from threading import Lock

_CONFIG_PATH = Path(__file__).parent.parent / "config.json"
_config_cache: dict = {}
_last_mtime: float = 0.0
_lock = Lock()


def _load_config() -> dict:
    """Load config from JSON file if modified."""
    global _config_cache, _last_mtime
    
    try:
        current_mtime = os.path.getmtime(_CONFIG_PATH)
    except OSError:
        return _config_cache
    
    with _lock:
        if current_mtime > _last_mtime:
            try:
                with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                    _config_cache = json.load(f)
                _last_mtime = current_mtime
            except (json.JSONDecodeError, OSError):
                pass
    
    return _config_cache


def get_config() -> dict:
    """Get the full config dictionary."""
    return _load_config().copy()


def get(key: str, default=None):
    """Get a config value by key."""
    return _load_config().get(key, default)
