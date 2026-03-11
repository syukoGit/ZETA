from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Optional

from ib_async import Contract, Ticker

from config import Phase, ResolvedPhaseConfig, config
from ibkr.ibTools import IBTools
from logger import get_logger
from utils.market_status import parse_market_snapshot


@dataclass
class ResolvedPhase:
    """Active phase together with its fully-merged execution configuration."""

    phase: Phase
    config: ResolvedPhaseConfig


logger = get_logger(__name__)

_VOLATILITY_FETCH_TIMEOUT_S = 20.0


async def _fetch_ticker(symbol: str, exchange: str, currency: str) -> Optional[Ticker]:
    """Request a delayed snapshot for the given contract. Returns None on any failure."""
    try:
        ibtools = IBTools.get_instance()
        ib = ibtools.ib

        async with ibtools.ib_sem:
            contract = Contract(
                secType="IND", symbol=symbol, exchange=exchange, currency=currency
            )
            await ib.qualifyContractsAsync(contract)

            ib.reqMarketDataType(
                3
            )  # delayed — reliable for indices without live subscription
            tickers = await asyncio.wait_for(
                ib.reqTickersAsync(contract, regulatorySnapshot=False),
                timeout=_VOLATILITY_FETCH_TIMEOUT_S,
            )
        if not tickers:
            logger.warning("phase_resolver: no ticker returned for %s", symbol)
            return None
        return tickers[0]
    except asyncio.TimeoutError:
        logger.warning(
            "phase_resolver: ticker fetch timed out for %s after %.1fs",
            symbol,
            _VOLATILITY_FETCH_TIMEOUT_S,
        )
        return None
    except Exception:
        logger.warning(
            "phase_resolver: failed to fetch ticker for %s", symbol, exc_info=True
        )
        return None


def _clean_price(value) -> Optional[float]:
    """Return float price or None when the value is missing / sentinel (-1)."""
    try:
        v = float(value)
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


async def _check_vix_above(threshold: float) -> bool:
    """Return True if the VIX last price exceeds *threshold*."""
    vix_index = next(
        (idx for idx in config().snapshot.indices if idx.symbol.upper() == "VIX"),
        None,
    )
    if vix_index is None:
        logger.warning(
            "phase_resolver: vix_above trigger configured but VIX not found in snapshot.indices"
        )
        return False

    ticker = await _fetch_ticker(
        vix_index.symbol, vix_index.exchange, vix_index.currency
    )
    if ticker is None:
        return False

    price = _clean_price(ticker.last) or _clean_price(ticker.close)
    if price is None:
        logger.warning("phase_resolver: VIX ticker returned no usable price")
        return False

    logger.debug("phase_resolver: VIX=%.2f, threshold=%.2f", price, threshold)
    return price > threshold


async def _check_high_volatility() -> bool:
    """
    Evaluate HIGH_VOLATILITY triggers in order. Short-circuits on first match.
    Any IBKR exception is caught per-trigger; failure => skip (fail-open = not HIGH_VOLATILITY).
    """
    triggers = config().phase_config.high_volatility.triggers
    for trigger in triggers:
        try:
            if trigger.vix_above is not None and await _check_vix_above(
                trigger.vix_above
            ):
                logger.info(
                    "phase_resolver: HIGH_VOLATILITY triggered (vix_above=%.1f)",
                    trigger.vix_above,
                )
                return True
        except Exception:
            logger.warning(
                "phase_resolver: exception evaluating trigger %s — skipping",
                trigger,
                exc_info=True,
            )

    return False


def _is_pre_market(now: datetime) -> bool:
    """
    Return True if *now* (UTC) falls within the configured pre-market window.
    The window is [start_utc, end_utc) and midnight-crossing is not supported
    (start must be < end).
    """
    pm = config().phase_config.pre_market
    h_s, m_s = map(int, pm.start_utc.split(":"))
    h_e, m_e = map(int, pm.end_utc.split(":"))
    start = time(h_s, m_s)
    end = time(h_e, m_e)
    current = now.astimezone(timezone.utc).time().replace(second=0, microsecond=0)
    return start <= current < end


def _resolve_phase_enum(now: datetime, snapshot: dict) -> Phase:
    """
    Resolve the active Phase enum from a pre-fetched snapshot.
    HIGH_VOLATILITY is intentionally excluded; it is injected by resolve_phase().
    """
    pc = config().phase_config
    any_open: bool = snapshot["any_open"]

    if any_open:
        earliest_open: Optional[datetime] = snapshot["earliest_current_open"]
        soonest_close: Optional[datetime] = snapshot["soonest_close"]

        if earliest_open is not None:
            minutes_since_open = (now - earliest_open).total_seconds() / 60
            if minutes_since_open < pc.opening_window.window_minutes:
                return Phase.OPENING_WINDOW

        if soonest_close is not None:
            minutes_before_close = (soonest_close - now).total_seconds() / 60
            if minutes_before_close < pc.closing_window.window_minutes:
                return Phase.CLOSING_WINDOW

        return Phase.MARKET_SESSION

    else:
        if _is_pre_market(now):
            return Phase.PRE_MARKET

        earliest_next_open: Optional[datetime] = snapshot["earliest_next_open"]
        if earliest_next_open is not None:
            hours_until_open = (earliest_next_open - now).total_seconds() / 3600
            if hours_until_open <= pc.off_market_short_threshold_hours:
                return Phase.OFF_MARKET_SHORT

        return Phase.OFF_MARKET_LONG


async def resolve_phase(now: datetime = None) -> ResolvedPhase:
    """
    Determine the active execution phase for the given moment and return it
    together with its fully-merged execution configuration.

    Priority order:
      1. HIGH_VOLATILITY  (only when at least one market is open)
      2. OPENING_WINDOW   (market open, within opening window duration)
      3. CLOSING_WINDOW   (market open, within closing window duration)
      4. MARKET_SESSION   (market open, outside both windows)
      5. PRE_MARKET       (market closed, within configured UTC time window)
      6. OFF_MARKET_SHORT (market closed, next open ≤ threshold hours away)
      7. OFF_MARKET_LONG  (market closed, next open > threshold hours away)

    Args:
        now: UTC-aware datetime to evaluate. Defaults to datetime.now(timezone.utc).

    Returns:
        ResolvedPhase with .phase (Phase enum) and .config (ResolvedPhaseConfig).
    """
    if now is None:
        now = datetime.now(timezone.utc)

    snapshot = parse_market_snapshot(now)

    # HIGH_VOLATILITY only applies when at least one market is open
    if snapshot["any_open"] and await _check_high_volatility():
        phase = Phase.HIGH_VOLATILITY
    else:
        phase = _resolve_phase_enum(now, snapshot)

    return ResolvedPhase(phase=phase, config=config().phases.resolved_phase(phase))


_current_phase: Optional[ResolvedPhase] = None


async def refresh_phase(now: datetime = None) -> ResolvedPhase:
    """
    Resolve the active phase and store it as the current phase.
    Call this once per run-loop iteration to update the cache.

    Returns:
        The freshly resolved ResolvedPhase (also cached internally).
    """
    global _current_phase
    _current_phase = await resolve_phase(now)
    logger.info("phase_resolver: current phase set to %s", _current_phase.phase.value)
    return _current_phase


def get_current_phase() -> ResolvedPhase:
    """
    Return the last phase resolved by refresh_phase().

    Raises:
        RuntimeError: if refresh_phase() has not been called yet.
    """
    if _current_phase is None:
        raise RuntimeError(
            "Current phase has not been initialised. Call refresh_phase() first."
        )
    return _current_phase
