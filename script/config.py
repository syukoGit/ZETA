import json
import logging
from copy import deepcopy
from pathlib import Path
from threading import Lock

_CONFIG_FILENAME = "config.json"
_config_cache: dict = {}
_last_mtime_ns: int = -1
_lock = Lock()
_logger = logging.getLogger(__name__)


DEFAULT_CONFIG: dict = {
    "debugPrint": False,
    "dry_run": True,
    "min_wait_seconds": 60,
    "default_wait_seconds": 600,
    "off_hours_wait_seconds": 3600,
    "llm": {
        "provider": "grok",
        "model": "grok-4-1-fast-reasoning",
    },
    "review": {
        "llm": {
            "provider": "grok",
            "model": "grok-4-1-fast-reasoning",
        },
        "every_n_trades": 5,
    },
    "embedding_model": "sentence-transformers/nli-bert-large",
    "ibkr": {
        "host": "127.0.0.1",
        "port": 7497,
        "clientId": 0,
        "min_cash_reserve": 0,
        "cash_reserve_currency": "BASE",
        "excluded_cash_currencies": [],
    },
}


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""


def _get_config_path() -> Path:
    return Path.cwd() / _CONFIG_FILENAME


def _write_json_atomic(path: Path, payload: dict) -> None:
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=4)
        f.write("\n")
    tmp_path.replace(path)


def _ensure_default_config_exists(path: Path) -> None:
    if path.exists():
        return
    _write_json_atomic(path, DEFAULT_CONFIG)


def _must_be_dict(payload: dict, key: str) -> dict:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"Invalid config: '{key}' must be an object")
    return value


def _must_be_bool(payload: dict, key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise ConfigError(f"Invalid config: '{key}' must be a boolean")
    return value


def _must_be_str(payload: dict, key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Invalid config: '{key}' must be a non-empty string")
    return value


def _must_be_int(payload: dict, key: str, *, min_value: int | None = None, max_value: int | None = None) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"Invalid config: '{key}' must be an integer")
    if min_value is not None and value < min_value:
        raise ConfigError(f"Invalid config: '{key}' must be >= {min_value}")
    if max_value is not None and value > max_value:
        raise ConfigError(f"Invalid config: '{key}' must be <= {max_value}")
    return value


def _must_be_number(payload: dict, key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"Invalid config: '{key}' must be a number")
    return float(value)


def _must_be_str_list(payload: dict, key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ConfigError(f"Invalid config: '{key}' must be an array of strings")
    return value


def _validate_config(payload: dict) -> None:
    _must_be_bool(payload, "debugPrint")
    _must_be_bool(payload, "dry_run")
    _must_be_int(payload, "min_wait_seconds", min_value=1)
    _must_be_int(payload, "default_wait_seconds", min_value=1)
    _must_be_int(payload, "off_hours_wait_seconds", min_value=1)
    _must_be_str(payload, "embedding_model")

    llm = _must_be_dict(payload, "llm")
    _must_be_str(llm, "provider")
    _must_be_str(llm, "model")

    review = _must_be_dict(payload, "review")
    review_llm = _must_be_dict(review, "llm")
    _must_be_str(review_llm, "provider")
    _must_be_str(review_llm, "model")
    _must_be_int(review, "every_n_trades", min_value=1)

    ibkr = _must_be_dict(payload, "ibkr")
    _must_be_str(ibkr, "host")
    _must_be_int(ibkr, "port", min_value=1, max_value=65535)
    _must_be_int(ibkr, "clientId", min_value=0)
    _must_be_number(ibkr, "min_cash_reserve")
    _must_be_str(ibkr, "cash_reserve_currency")
    _must_be_str_list(ibkr, "excluded_cash_currencies")


def _load_config() -> dict:
    """Load config from current working directory and hot-reload on change."""
    global _config_cache, _last_mtime_ns

    config_path = _get_config_path()

    with _lock:
        _ensure_default_config_exists(config_path)

        try:
            current_mtime_ns = config_path.stat().st_mtime_ns
        except OSError as exc:
            raise ConfigError(
                f"Unable to access config file '{config_path}' from cwd '{Path.cwd()}': {exc}"
            ) from exc

        if current_mtime_ns != _last_mtime_ns:
            previous_mtime_ns = _last_mtime_ns
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
            except json.JSONDecodeError as exc:
                raise ConfigError(
                    f"Invalid JSON in config file '{config_path}': {exc}"
                ) from exc
            except OSError as exc:
                raise ConfigError(
                    f"Unable to read config file '{config_path}' from cwd '{Path.cwd()}': {exc}"
                ) from exc

            if not isinstance(loaded, dict):
                raise ConfigError(
                    f"Invalid config file '{config_path}': root value must be a JSON object"
                )

            _validate_config(loaded)
            _config_cache = loaded
            _last_mtime_ns = current_mtime_ns
            if previous_mtime_ns == -1:
                _logger.info("Runtime config loaded from %s", config_path)
            else:
                _logger.info("Runtime config reloaded from %s", config_path)

    return _config_cache


def get_config() -> dict:
    """Get the full config dictionary."""
    return deepcopy(_load_config())


def get(key: str, default=None):
    """Get a config value by key."""
    return _load_config().get(key, default)
