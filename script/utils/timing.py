import asyncio
from datetime import datetime, timezone

from config import config
from logger import get_logger, dynamic_log, dynamic_log_end
from phase_resolver import get_current_phase, refresh_phase
from utils.market_status import parse_market_snapshot

logger = get_logger(__name__)


_FALLBACK_MAX_WAIT = 3600
_FALLBACK_MIN_WAIT = 60


def _off_hours_wait() -> int:
    try:
        return get_current_phase().config.run_interval.max
    except RuntimeError:
        return _FALLBACK_MAX_WAIT


def _min_wait() -> int:
    try:
        return get_current_phase().config.run_interval.min
    except RuntimeError:
        return _FALLBACK_MIN_WAIT


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
                wait,
                latest_close.strftime("%H:%M"),
            )
            return max(_min_wait(), wait)

    return max(_min_wait(), time_before_next_run)


async def wait_with_phase_monitoring(wait_seconds: int) -> None:
    initial_phase = get_current_phase().phase
    poll_interval = config().phase_config.phase_poll_interval_s

    remaining = wait_seconds
    seconds_since_last_check = 0
    refresh_task: asyncio.Task | None = None

    while remaining > 0:
        mins, secs = divmod(remaining, 60)
        dynamic_log("Next call in %02d:%02d", int(mins), int(secs))

        await asyncio.sleep(1)
        remaining -= 1

        # If a background refresh just finished, inspect the result
        if refresh_task is not None and refresh_task.done():
            try:
                refresh_task.result()
            except Exception:
                logger.warning(
                    "phase_resolver: refresh_phase raised during wait", exc_info=True
                )
            refresh_task = None
            seconds_since_last_check = 0
            new_phase = get_current_phase().phase
            if new_phase != initial_phase:
                dynamic_log_end()
                logger.info(
                    "Phase changed from %s to %s during wait — triggering early run",
                    initial_phase.value,
                    new_phase.value,
                )
                return

        # Launch a new refresh when the interval is reached and no refresh is running
        if refresh_task is None:
            seconds_since_last_check += 1
            if seconds_since_last_check >= poll_interval:
                refresh_task = asyncio.create_task(refresh_phase())

    if refresh_task is not None and not refresh_task.done():
        refresh_task.cancel()

    dynamic_log_end()
