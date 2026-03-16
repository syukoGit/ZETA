import asyncio
from dataclasses import dataclass, field
import logging
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from config import SnapshotIndex, config
from llm.tools.ibkr.get_quote import get_quote
from llm.tools.ibkr.get_cash_balance import get_cash_balance
from llm.tools.ibkr.get_open_trades import get_open_trades
from llm.tools.ibkr.get_pnl import get_pnl
from llm.tools.ibkr.get_positions import get_positions
from llm.tools.utils.get_date_hour_utc_and_markets import get_date_hour_utc_and_markets
from llm.tools.history.get_runs_to_review import get_runs_to_review
from phase_resolver import get_current_phase
from utils.json_utils import dumps_json
from utils.market_status import parse_market_snapshot

logger = logging.getLogger(__name__)


@dataclass
class DataContext:
    _date_hour_and_markets: asyncio.Task[dict[str, Any]] | None = field(
        default=None, init=False
    )

    async def get_date_hour_and_markets(self) -> dict[str, Any]:
        if self._date_hour_and_markets is None:
            self._date_hour_and_markets = asyncio.create_task(
                get_date_hour_utc_and_markets({})
            )
        return await self._date_hour_and_markets


async def _fetch_current_datetime(data_context: DataContext) -> str:
    data = await data_context.get_date_hour_and_markets()
    return data["date_and_hour"]


async def _fetch_market_status(data_context: DataContext) -> str:
    data = await data_context.get_date_hour_and_markets()
    return dumps_json(data["markets"])


async def _fetch_next_market_close(_) -> str:
    snapshot = parse_market_snapshot(datetime.now(timezone.utc))
    close = snapshot.get("soonest_close")
    return close.strftime("%Y-%m-%d %H:%M UTC") if close else "N/A"


async def _fetch_cash_balance(_) -> str:
    result = await get_cash_balance({})
    return dumps_json(result["cash_balances"])


async def _fetch_positions(_) -> str:
    result = await get_positions({})
    return dumps_json(result["positions"])


async def _fetch_open_trades(_) -> str:
    result = await get_open_trades({})
    return dumps_json(result["open_trades"])


async def _fetch_pnl(_) -> str:
    result = await get_pnl({})
    return dumps_json(result["pnl"])


async def _fetch_runs_to_review(_) -> str:
    result = await get_runs_to_review({})
    return dumps_json(result)


async def _fetch_current_phase(_) -> str:
    return get_current_phase().phase.value


async def _fetch_current_phase_min(_) -> str:
    return str(get_current_phase().config.run_interval.min)


async def _fetch_current_phase_max(_) -> str:
    return str(get_current_phase().config.run_interval.max)


async def _fetch_quotes(_) -> str:
    # Fetch index quotes concurrently (with a bounded concurrency limit)
    semaphore = asyncio.Semaphore(5)

    async def fetch_for_index(idx: SnapshotIndex) -> tuple[str, Any | None]:
        async with semaphore:
            try:
                result = await get_quote(
                    {
                        "symbol": idx.symbol,
                        "exchange": idx.exchange,
                        "currency": idx.currency,
                    }
                )
                if isinstance(result, dict):
                    return idx.symbol, result.get("last")
                else:
                    logger.error(
                        "get_quote for index %s returned non-dict result: %r",
                        idx.symbol,
                        result,
                    )
                    return idx.symbol, None
            except Exception:
                logger.exception("Failed to fetch quote for index %s", idx.symbol)
                return idx.symbol, None

    indices = list(config().snapshot.indices)
    tasks = [asyncio.create_task(fetch_for_index(idx)) for idx in indices]
    results = await asyncio.gather(*tasks)

    lines: list[str] = []
    for symbol, last in results:
        value = f"{last:,.2f}" if isinstance(last, (int, float)) else "N/A"
        lines.append(f"{symbol}: {value}")

    return "\n".join(lines)


_FETCHERS: dict[str, Callable[[DataContext], Awaitable[str]]] = {
    "current_phase": _fetch_current_phase,
    "phase.min": _fetch_current_phase_min,
    "phase.max": _fetch_current_phase_max,
    "current_datetime": _fetch_current_datetime,
    "market_status": _fetch_market_status,
    "next_market_close": _fetch_next_market_close,
    "cash_balance": _fetch_cash_balance,
    "positions": _fetch_positions,
    "open_trades": _fetch_open_trades,
    "pnl": _fetch_pnl,
    "runs_to_review": _fetch_runs_to_review,
    "quotes": _fetch_quotes,
}


def _extract_template_keys(template: str) -> set[str]:
    return set(re.findall(r"\{\{([\w.]+)\}\}", template))


async def build_context(template: str, static_vars: dict[str, str]) -> dict[str, str]:
    data_context = DataContext()
    needed_keys = _extract_template_keys(template) - static_vars.keys()

    for key in needed_keys:
        if key not in _FETCHERS:
            logger.warning("No fetcher registered for template variable: {{%s}}", key)

    fetcher_tasks: dict[str, asyncio.Task] = {
        k: asyncio.create_task(_FETCHERS[k](data_context))
        for k in needed_keys
        if k in _FETCHERS
    }
    if fetcher_tasks:
        await asyncio.gather(*fetcher_tasks.values(), return_exceptions=True)

    resolved: dict[str, str] = dict(static_vars)
    for key in needed_keys:
        if key not in _FETCHERS:
            continue
        task = fetcher_tasks[key]
        if task.cancelled():
            logger.error("Fetcher '%s' was cancelled", key)
            resolved[key] = "N/A"
            continue
        exc = task.exception()
        if exc is not None:
            logger.error(
                "Fetcher '%s' failed with exception",
                key,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            resolved[key] = "N/A"
            continue
        try:
            resolved[key] = str(task.result())
        except Exception:
            logger.error("Fetcher for {{%s}} raised", key, exc_info=True)
            resolved[key] = "N/A"

    return resolved
