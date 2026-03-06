import json
import logging
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

_CONFIG_FILENAME = "config.json"
_config_cache: "AppConfig | None" = None
_last_mtime_ns: int = -1
_lock = Lock()
_logger = logging.getLogger(__name__)


class ConfigError(RuntimeError):
    """Raised when configuration is missing or invalid."""

def _fk(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _require_bool(d: dict, key: str, path: str) -> bool:
    v = d.get(key)
    if not isinstance(v, bool):
        raise ConfigError(f"Invalid config: '{_fk(path, key)}' must be a boolean")
    return v


def _require_str(d: dict, key: str, path: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ConfigError(f"Invalid config: '{_fk(path, key)}' must be a non-empty string")
    return v


def _require_int(
    d: dict,
    key: str,
    path: str,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    v = d.get(key)
    if not isinstance(v, int) or isinstance(v, bool):
        raise ConfigError(f"Invalid config: '{_fk(path, key)}' must be an integer")
    if min_value is not None and v < min_value:
        raise ConfigError(f"Invalid config: '{_fk(path, key)}' must be >= {min_value}")
    if max_value is not None and v > max_value:
        raise ConfigError(f"Invalid config: '{_fk(path, key)}' must be <= {max_value}")
    return v


def _require_number(d: dict, key: str, path: str) -> float:
    v = d.get(key)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ConfigError(f"Invalid config: '{_fk(path, key)}' must be a number")
    return float(v)


def _require_dict(d: dict, key: str, path: str) -> dict:
    v = d.get(key)
    if not isinstance(v, dict):
        raise ConfigError(f"Invalid config: '{_fk(path, key)}' must be an object")
    return v


def _require_str_list(d: dict, key: str, path: str) -> list[str]:
    v = d.get(key)
    if not isinstance(v, list) or any(not isinstance(item, str) for item in v):
        raise ConfigError(f"Invalid config: '{_fk(path, key)}' must be an array of strings")
    return v


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str

    @classmethod
    def from_dict(cls, d: dict, path: str) -> "LLMConfig":
        return cls(
            provider=_require_str(d, "provider", path),
            model=_require_str(d, "model", path),
        )


@dataclass(frozen=True)
class ReviewConfig:
    llm: LLMConfig
    every_n_trades: int

    @classmethod
    def from_dict(cls, d: dict, path: str = "review") -> "ReviewConfig":
        return cls(
            llm=LLMConfig.from_dict(_require_dict(d, "llm", path), path=f"{path}.llm"),
            every_n_trades=_require_int(d, "every_n_trades", path, min_value=1),
        )


@dataclass(frozen=True)
class SnapshotIndexConfig:
    symbol: str
    exchange: str
    currency: str

    @classmethod
    def from_dict(cls, d: dict, path: str) -> "SnapshotIndexConfig":
        symbol = _require_str(d, "symbol", path)
        exchange = _require_str(d, "exchange", path)
        currency = d.get("currency", "USD")
        if not isinstance(currency, str) or not currency.strip():
            raise ConfigError(f"Invalid config: '{_fk(path, 'currency')}' must be a non-empty string")
        return cls(symbol=symbol, exchange=exchange, currency=currency)


@dataclass(frozen=True)
class SnapshotConfig:
    indices: tuple["SnapshotIndexConfig", ...]

    @classmethod
    def from_dict(cls, d: dict, path: str = "snapshot") -> "SnapshotConfig":
        raw = d.get("indices")
        if not isinstance(raw, list):
            raise ConfigError(f"Invalid config: '{_fk(path, 'indices')}' must be an array")
        indices_list = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                raise ConfigError(f"Invalid config: '{path}.indices[{i}]' must be an object")
            indices_list.append(SnapshotIndexConfig.from_dict(item, path=f"{path}.indices[{i}]"))
        return cls(indices=tuple(indices_list))


@dataclass(frozen=True)
class IBKRConfig:
    host: str
    port: int
    client_id: int
    min_cash_reserve: float
    cash_reserve_currency: str
    excluded_cash_currencies: tuple[str, ...]

    @classmethod
    def from_dict(cls, d: dict, path: str = "ibkr") -> "IBKRConfig":
        return cls(
            host=_require_str(d, "host", path),
            port=_require_int(d, "port", path, min_value=1, max_value=65535),
            client_id=_require_int(d, "clientId", path, min_value=0),
            min_cash_reserve=_require_number(d, "min_cash_reserve", path),
            cash_reserve_currency=_require_str(d, "cash_reserve_currency", path),
            excluded_cash_currencies=tuple(_require_str_list(d, "excluded_cash_currencies", path)),
        )


@dataclass(frozen=True)
class AppConfig:
    debug_print: bool
    dry_run: bool
    min_wait_seconds: int
    default_wait_seconds: int
    off_hours_wait_seconds: int
    embedding_model: str
    llm: LLMConfig
    review: ReviewConfig
    ibkr: IBKRConfig
    snapshot: SnapshotConfig

    @classmethod
    def from_dict(cls, d: dict) -> "AppConfig":
        return cls(
            debug_print=_require_bool(d, "debugPrint", ""),
            dry_run=_require_bool(d, "dry_run", ""),
            min_wait_seconds=_require_int(d, "min_wait_seconds", "", min_value=1),
            default_wait_seconds=_require_int(d, "default_wait_seconds", "", min_value=1),
            off_hours_wait_seconds=_require_int(d, "off_hours_wait_seconds", "", min_value=1),
            embedding_model=_require_str(d, "embedding_model", ""),
            llm=LLMConfig.from_dict(_require_dict(d, "llm", ""), path="llm"),
            review=ReviewConfig.from_dict(_require_dict(d, "review", "")),
            ibkr=IBKRConfig.from_dict(_require_dict(d, "ibkr", "")),
            snapshot=SnapshotConfig.from_dict(_require_dict(d, "snapshot", "")),
        )

_DEFAULT_CONFIG: dict = {
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
    "snapshot": {
        "indices": [],
    },
}



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
    _write_json_atomic(path, _DEFAULT_CONFIG)

def _load_config() -> "AppConfig":
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

            _config_cache = AppConfig.from_dict(loaded)
            _last_mtime_ns = current_mtime_ns
            if previous_mtime_ns == -1:
                _logger.info("Runtime config loaded from %s", config_path)
            else:
                _logger.info("Runtime config reloaded from %s", config_path)

    return _config_cache


def config() -> "AppConfig":
    return _load_config()
