from __future__ import annotations

import logging
import threading
from enum import Enum
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
    provider: str = "grok"
    model: str = "grok-4-1-fast-reasoning"


class ReviewConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)


class RunIntervalConfig(BaseModel):
    min: int = 60
    max: int = 300


class PhaseToolsConfig(BaseModel):
    disable: list[str] = Field(default_factory=list)


class PhaseReviewConfig(BaseModel):
    runs_before_review: int = 15


class DefaultPhaseConfig(BaseModel):
    run_interval: RunIntervalConfig = Field(default_factory=RunIntervalConfig)
    review: PhaseReviewConfig = Field(default_factory=PhaseReviewConfig)
    tools: PhaseToolsConfig = Field(default_factory=PhaseToolsConfig)


class PhaseOverrideConfig(BaseModel):
    run_interval: Optional[RunIntervalConfig] = None
    review: Optional[PhaseReviewConfig] = None
    tools: Optional[PhaseToolsConfig] = None
    prompt_file: str = ""


class HighVolatilityTrigger(BaseModel):
    vix_above: Optional[float] = None
    index_move_pct: Optional[float] = None


class PreMarketConfig(BaseModel):
    start_utc: str = Field(
        default="12:00",
        description="Start of the pre-market window in UTC (HH:MM)",
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
    )
    end_utc: str = Field(
        default="13:30",
        description="End of the pre-market window in UTC (HH:MM, exclusive)",
        pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$",
    )


class WindowConfig(BaseModel):
    window_minutes: int = Field(
        default=30, gt=0, description="Duration of the window in minutes"
    )


class HighVolatilityResolverConfig(BaseModel):
    triggers: list[HighVolatilityTrigger] = Field(default_factory=list)


class PhaseConfig(BaseModel):
    off_market_short_threshold_hours: int = Field(
        default=6,
        gt=0,
        description="Hours before next open below which OFF_MARKET_SHORT is active",
    )
    pre_market: PreMarketConfig = Field(default_factory=PreMarketConfig)
    opening_window: WindowConfig = Field(default_factory=WindowConfig)
    closing_window: WindowConfig = Field(default_factory=WindowConfig)
    high_volatility: HighVolatilityResolverConfig = Field(
        default_factory=HighVolatilityResolverConfig
    )


class ResolvedPhaseConfig(BaseModel):
    run_interval: RunIntervalConfig
    review: PhaseReviewConfig
    tools: PhaseToolsConfig
    prompt_file: str


class Phase(str, Enum):
    PRE_MARKET = "PRE_MARKET"
    OPENING_WINDOW = "OPENING_WINDOW"
    MARKET_SESSION = "MARKET_SESSION"
    CLOSING_WINDOW = "CLOSING_WINDOW"
    OFF_MARKET_SHORT = "OFF_MARKET_SHORT"
    OFF_MARKET_LONG = "OFF_MARKET_LONG"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"


class PhasesConfig(BaseModel):
    default: DefaultPhaseConfig = Field(default_factory=DefaultPhaseConfig)
    PRE_MARKET: PhaseOverrideConfig = Field(default_factory=PhaseOverrideConfig)
    OPENING_WINDOW: PhaseOverrideConfig = Field(default_factory=PhaseOverrideConfig)
    MARKET_SESSION: PhaseOverrideConfig = Field(default_factory=PhaseOverrideConfig)
    CLOSING_WINDOW: PhaseOverrideConfig = Field(default_factory=PhaseOverrideConfig)
    OFF_MARKET_SHORT: PhaseOverrideConfig = Field(default_factory=PhaseOverrideConfig)
    OFF_MARKET_LONG: PhaseOverrideConfig = Field(default_factory=PhaseOverrideConfig)
    HIGH_VOLATILITY: PhaseOverrideConfig = Field(default_factory=PhaseOverrideConfig)

    def resolved_phase(self, phase: Phase | str) -> ResolvedPhaseConfig:
        """Merge default config with the phase override (phase wins on non-None fields)."""
        phase_name = phase.value if isinstance(phase, Phase) else phase
        override: PhaseOverrideConfig = getattr(self, phase_name)
        d = self.default

        return ResolvedPhaseConfig(
            run_interval=(
                override.run_interval
                if override.run_interval is not None
                else d.run_interval
            ),
            review=override.review if override.review is not None else d.review,
            tools=override.tools if override.tools is not None else d.tools,
            prompt_file=override.prompt_file,
        )


class IBKRConfig(BaseModel):
    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 0
    min_cash_reserve: float = 500.0
    cash_reserve_currency: str = "USD"
    excluded_cash_currencies: list[str] = Field(default_factory=list)


class SnapshotIndex(BaseModel):
    symbol: str
    exchange: str
    currency: str = "USD"


class SnapshotConfig(BaseModel):
    indices: list[SnapshotIndex] = Field(default_factory=list)


class AppConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    debug_print: bool = Field(default=False, alias="debugPrint")
    dry_run: bool = True
    llm: LLMConfig = Field(default_factory=LLMConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    embedding_model: str = "sentence-transformers/nli-bert-large"
    ibkr: IBKRConfig = Field(default_factory=IBKRConfig)
    snapshot: SnapshotConfig = Field(default_factory=SnapshotConfig)
    phases: PhasesConfig = Field(default_factory=PhasesConfig)
    phase_config: PhaseConfig = Field(default_factory=PhaseConfig)


_lock = threading.RLock()
_current_config: Optional[AppConfig] = None


def _load_config() -> AppConfig:
    if not _CONFIG_PATH.exists():
        default_cfg = AppConfig()
        raw_dict = default_cfg.model_dump(by_alias=True, exclude_none=True)
        _CONFIG_PATH.write_text(
            yaml.dump(
                raw_dict, default_flow_style=False, allow_unicode=True, sort_keys=False
            ),
            encoding="utf-8",
        )
        logger.warning(
            "config.yaml not found — created default config at %s", _CONFIG_PATH
        )
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
