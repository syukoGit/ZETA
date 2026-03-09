from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field
from pydantic import ConfigDict
from watchdog.events import FileSystemEventHandler, FileModifiedEvent
from watchdog.observers import Observer

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


class LLMConfig(BaseModel):
    provider: str
    model: str


class ReviewConfig(BaseModel):
    llm: LLMConfig
    every_n_trades: int


class IBKRConfig(BaseModel):
    host: str
    port: int
    clientId: int
    min_cash_reserve: float
    cash_reserve_currency: str
    excluded_cash_currencies: list[str]


class SnapshotIndex(BaseModel):
    symbol: str
    exchange: str
    currency: str = "USD"


class SnapshotConfig(BaseModel):
    indices: list[SnapshotIndex]


class AppConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    debug_print: bool = Field(alias="debugPrint")
    dry_run: bool
    min_wait_seconds: int
    default_wait_seconds: int
    off_hours_wait_seconds: int
    llm: LLMConfig
    review: ReviewConfig
    embedding_model: str
    ibkr: IBKRConfig
    snapshot: SnapshotConfig


_lock = threading.RLock()
_current_config: Optional[AppConfig] = None


def _load_config() -> AppConfig:
    with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return AppConfig.model_validate(raw)


def config() -> AppConfig:
    global _current_config
    if _current_config is None:
        with _lock:
            if _current_config is None:
                _current_config = _load_config()
                logger.debug("Config loaded from %s", _CONFIG_PATH)
    return _current_config


def _reload_config() -> None:
    global _current_config
    try:
        new_cfg = _load_config()
        with _lock:
            _current_config = new_cfg
        logger.info("Config reloaded from %s", _CONFIG_PATH)
    except Exception as exc:
        logger.error("Config reload failed - keeping previous config. Error: %s", exc)


# Config file watcher for hot-reloading
class _ConfigFileHandler(FileSystemEventHandler):
    def on_modified(self, event: FileModifiedEvent) -> None:
        if Path(event.src_path).resolve() == _CONFIG_PATH.resolve():
            _reload_config()


def start_config_watcher() -> None:
    observer = Observer()
    observer.schedule(
        _ConfigFileHandler(),
        path=str(_CONFIG_PATH.parent),
        recursive=False,
    )
    observer.daemon = True
    observer.start()
    logger.info("Config watcher started (watching %s)", _CONFIG_PATH)
