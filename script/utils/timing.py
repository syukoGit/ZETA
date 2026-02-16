import asyncio
import sys
from datetime import datetime, timezone

from config import get
from logger import get_logger
from utils.market_status import parse_market_snapshot

logger = get_logger(__name__)


def _off_hours_wait() -> int:
    return get("off_hours_wait_seconds", 3600)

def _min_wait() -> int:
    return get("min_wait_seconds", 60)


def is_trading_hours(now: datetime = None) -> bool:
    """
    Check whether any monitored exchange is currently open.

    Args:
        now: The datetime to check (timezone-aware, UTC).
             If None, uses the current UTC time.

    Returns:
        True if at least one exchange is open, False otherwise.
    """
    return parse_market_snapshot(now)["any_open"]


def get_wait_time(time_before_next_run: int) -> int:
    """
    Calculate the wait time before the next iteration, taking real
    exchange schedules into account.

    - If markets are closed: wait until the next exchange opens
      (capped at off_hours_wait_seconds).
    - If markets are open: use the requested time, but never schedule
      the next call after all exchanges have closed.

    Args:
        time_before_next_run: Desired wait time in seconds.

    Returns:
        Adjusted wait time in seconds.
    """
    now = datetime.now(timezone.utc)
    snapshot = parse_market_snapshot(now)

    if not snapshot["any_open"]:
        # --- Markets are closed ---
        next_open = snapshot["earliest_next_open"]
        if next_open is not None:
            seconds_until_open = (next_open - now).total_seconds()
            wait = min(int(seconds_until_open), _off_hours_wait())
            logger.debug(
                "Markets closed (%s). Next open: %s. Wait: %ds",
                now.strftime("%H:%M"),
                next_open.strftime("%Y-%m-%d %H:%M"),
                wait,
            )
            return max(_min_wait(), wait)

        logger.debug("Markets closed, no next open found. Wait: %ds", _off_hours_wait())
        return _off_hours_wait()

    # --- Markets are open ---
    logger.debug("Markets open. Requested wait: %ds", time_before_next_run)

    latest_close = snapshot["latest_close"]
    if latest_close is not None:
        seconds_until_close = (latest_close - now).total_seconds()
        if time_before_next_run > seconds_until_close:
            wait = int(seconds_until_close)
            logger.debug(
                "Adjusted to %ds to not exceed market close at %s",
                wait, latest_close.strftime("%H:%M"),
            )
            return max(_min_wait(), wait)

    return max(_min_wait(), time_before_next_run)


async def countdown_display(wait_seconds: int) -> None:
    """
    Display a countdown in the console.
    
    Args:
        wait_seconds: Number of seconds to wait.
    """
    current_hour = datetime.now(timezone.utc).strftime("%H:%M")
    remaining = wait_seconds
    
    while remaining > 0:
        mins, secs = divmod(remaining, 60)
        status_msg = f"\r⏳ {current_hour} - Next call in {int(mins):02d}:{int(secs):02d}  "
        sys.stdout.write(status_msg)
        sys.stdout.flush()
        
        await asyncio.sleep(1)
        remaining -= 1
    
    # New line after the countdown
    print()
