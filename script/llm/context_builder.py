import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable

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


async def _fetch_current_datetime() -> str:
    result = await get_date_hour_utc_and_markets({})
    return result["date_and_hour"]


async def _fetch_market_status() -> str:
    result = await get_date_hour_utc_and_markets({})
    return dumps_json(result["markets"])


async def _fetch_next_market_close() -> str:
    snapshot = parse_market_snapshot(datetime.now(timezone.utc))
    close = snapshot.get("soonest_close")
    return close.strftime("%Y-%m-%d %H:%M UTC") if close else "N/A"


async def _fetch_cash_balance() -> str:
    result = await get_cash_balance({})
    return dumps_json(result["cash_balances"])


async def _fetch_positions() -> str:
    result = await get_positions({})
    return dumps_json(result["positions"])


async def _fetch_open_trades() -> str:
    result = await get_open_trades({})
    return dumps_json(result["open_trades"])


async def _fetch_pnl() -> str:
    result = await get_pnl({})
    return dumps_json(result["pnl"])


async def _fetch_runs_to_review() -> str:
    result = await get_runs_to_review({})
    return dumps_json(result)


async def _fetch_current_phase() -> str:
    return get_current_phase().phase.value


async def _fetch_current_phase_min() -> str:
    return str(get_current_phase().config.run_interval.min)


async def _fetch_current_phase_max() -> str:
    return str(get_current_phase().config.run_interval.max)


_FETCHERS: dict[str, Callable[[], Awaitable[str]]] = {
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
}


def _extract_template_keys(template: str) -> set[str]:
    return set(re.findall(r"\{\{([\w.]+)\}\}", template))


async def build_context(template: str, static_vars: dict[str, str]) -> dict[str, str]:
    needed_keys = _extract_template_keys(template) - static_vars.keys()

    for key in needed_keys:
        if key not in _FETCHERS:
            logger.warning("No fetcher registered for template variable: {{%s}}", key)

    fetcher_tasks: dict[str, asyncio.Task] = {
        k: asyncio.create_task(_FETCHERS[k]()) for k in needed_keys if k in _FETCHERS
    }
    if fetcher_tasks:
        await asyncio.gather(*fetcher_tasks.values(), return_exceptions=True)

    resolved: dict[str, str] = dict(static_vars)
    for key in needed_keys:
        if key not in _FETCHERS:
            continue
        task = fetcher_tasks[key]
        exc = task.exception() if not task.cancelled() else None
        if task.cancelled() or exc is not None:
            logger.error("Fetcher '%s' failed: %s", key, exc)
            resolved[key] = "N/A"
            continue
        try:
            resolved[key] = str(task.result())
        except Exception as e:
            logger.error("Fetcher for {{%s}} raised: %s", key, e)
            resolved[key] = "N/A"

    return resolved
