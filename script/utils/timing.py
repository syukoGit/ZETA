"""
Timing management module for the main loop.
Handles trading hours and wait time calculations.
"""

import asyncio
import sys
from datetime import datetime, time as dt_time, timedelta, timezone

from logger import get_logger

logger = get_logger(__name__)


# Trading hours
EVENING_CUTOFF = dt_time(21, 30)
MORNING_START = dt_time(13, 0)

# Default wait times (in seconds)
DEFAULT_WAIT_TIME = 600
OFF_HOURS_WAIT_TIME = 3600


def is_trading_hours(current_time: dt_time = None) -> bool:
    """
    Check whether we are within trading hours (13:00 - 21:30).
    
    Args:
        current_time: The time to check. If None, uses the current time.
    
    Returns:
        True if within trading hours, False otherwise.
    """
    if current_time is None:
        current_time = datetime.now(timezone.utc).time()
    
    return MORNING_START <= current_time < EVENING_CUTOFF


def get_wait_time(time_before_next_run: int) -> int:
    """
    Calculate the wait time before the next call, taking trading hours
    into account.
    
    - Between 22:30 and 15:00: wait 1 hour (or until 15:00)
    - Between 15:00 and 22:30: use the requested time (or until 22:30)
    
    Args:
        time_before_next_run: Desired wait time in seconds.
    
    Returns:
        Adjusted wait time in seconds.
    """
    now = datetime.now(timezone.utc)
    current_time = now.time()
    
    if not is_trading_hours(current_time):
        # Outside trading hours
        logger.debug("Outside trading hours (%s). Wait: %ds", current_time.strftime("%H:%M"), OFF_HOURS_WAIT_TIME)
        next_call = now + timedelta(seconds=OFF_HOURS_WAIT_TIME)
        
        if current_time < MORNING_START:
            # Before 15:00 - check if we can wait until 15:00
            target_15h = datetime.combine(now.date(), MORNING_START)
            if next_call > target_15h:
                wait_seconds = (target_15h - now).total_seconds()
                logger.debug("Adjusted to %ds to resume at 15:00", wait_seconds)
                return max(60, int(wait_seconds))
        
        return OFF_HOURS_WAIT_TIME
    else:
        # During trading hours
        logger.debug("Trading hours active. Requested wait: %ds", time_before_next_run)
        next_call = now + timedelta(seconds=time_before_next_run)
        target_22h30 = datetime.combine(now.date(), EVENING_CUTOFF)
        
        if next_call.time() > EVENING_CUTOFF:
            # The next call would exceed 22:30
            wait_seconds = (target_22h30 - now).total_seconds()
            logger.debug("Adjusted to %ds to not exceed 22:30", wait_seconds)
            return max(60, int(wait_seconds))
        
        return time_before_next_run


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
