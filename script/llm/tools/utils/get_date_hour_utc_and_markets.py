from datetime import datetime, timezone
from typing import Any, Dict

import exchange_calendars as xc
import pandas as pd

from llm.tools.base import register_tool


EXCHANGES_CALENDARS = {
    "NASDAQ": "XNAS",
    "NYSE": "XNYS",
    "AMEX": "XASE",
}


def _get_next_session_open(calendar: xc.ExchangeCalendar, now: datetime) -> datetime | None:
    """
    Find the next session open time from a given datetime.
    
    Works correctly even on non-trading days (weekends, holidays).
    If the market is currently open, returns the next session after the current one.
    If the market is closed but today's session hasn't opened yet, returns today's open.
    
    Args:
        calendar: An exchange_calendars calendar instance.
        now: The current datetime (timezone-aware, UTC).
    
    Returns:
        The next session open as a timezone-aware datetime, or None if not found.
    """
    today = pd.Timestamp(now.date())
    session = calendar.date_to_session(today, direction="next")
    open_time = calendar.session_open(session)

    if open_time > now:
        return open_time.to_pydatetime()

    # Today's session already started or passed, find the next trading day
    next_day = session + pd.Timedelta(days=1)
    next_session = calendar.date_to_session(next_day, direction="next")
    return calendar.session_open(next_session).to_pydatetime()


def _get_market_status(now: datetime) -> Dict[str, Any]:
    statuses = {}
    ts = now.astimezone(timezone.utc)

    for name, mic in EXCHANGES_CALENDARS.items():
        calendar = xc.get_calendar(mic)

        try:
            is_open = calendar.is_open_on_minute(ts)
            if is_open:
                close_time = calendar.session_close(calendar.minute_to_session(ts))
                next_open = _get_next_session_open(calendar, ts)
                statuses[name] = {
                    "status": "OPEN",
                    "closes_at_utc": close_time.strftime("%H:%M"),
                    "next_session_open_utc": next_open.strftime("%Y-%m-%d %H:%M") if next_open else None,
                }
            else:
                next_open = _get_next_session_open(calendar, ts)
                statuses[name] = {
                    "status": "CLOSED",
                    "next_session_open_utc": next_open.strftime("%Y-%m-%d %H:%M") if next_open else None,
                }
        except Exception as e:
            print(f"Error checking market status for {name}: {e}")
            statuses[name] = {"status": "UNKNOWN"}
    return statuses
        

@register_tool("get_date_hour_utc_and_markets", description="Get the current UTC date/time and the open/closed status of major stock exchanges")
async def get_date_hour_utc_and_markets(_: Dict[str, Any]) -> Dict[str, str]:
    now = datetime.now(timezone.utc)

    return {
        "date_and_hour": now.strftime("%Y-%m-%d %H:%M:%S"),
        "markets": _get_market_status(now),
    }