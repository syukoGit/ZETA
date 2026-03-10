from datetime import datetime, timezone
from typing import Any, Dict

import exchange_calendars as xc
import pandas as pd


EXCHANGES_CALENDARS: Dict[str, str] = {
    "NASDAQ": "XNAS",
    "NYSE": "XNYS",
    "AMEX": "XASE",
}


def get_next_session_open(
    calendar: xc.ExchangeCalendar, now: datetime
) -> datetime | None:
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


def get_market_status(now: datetime) -> Dict[str, Any]:
    """
    Return the open/closed status and timing info for each monitored exchange.

    Args:
        now: The current datetime (timezone-aware, UTC).

    Returns:
        A dict keyed by exchange name, each value containing:
            - status: "OPEN", "CLOSED", or "UNKNOWN"
            - closes_at_utc: str (HH:MM) if OPEN
            - next_session_open_utc: str (YYYY-MM-DD HH:MM)
    """
    statuses = {}
    ts = now.astimezone(timezone.utc)

    for name, mic in EXCHANGES_CALENDARS.items():
        calendar = xc.get_calendar(mic)

        try:
            is_open = calendar.is_open_on_minute(ts)
            if is_open:
                session = calendar.minute_to_session(ts)
                open_time = calendar.session_open(session)
                close_time = calendar.session_close(session)
                next_open = get_next_session_open(calendar, ts)
                statuses[name] = {
                    "status": "OPEN",
                    "opened_at_utc": open_time.strftime("%H:%M"),
                    "closes_at_utc": close_time.strftime("%H:%M"),
                    "next_session_open_utc": (
                        next_open.strftime("%Y-%m-%d %H:%M") if next_open else None
                    ),
                }
            else:
                next_open = get_next_session_open(calendar, ts)
                statuses[name] = {
                    "status": "CLOSED",
                    "next_session_open_utc": (
                        next_open.strftime("%Y-%m-%d %H:%M") if next_open else None
                    ),
                }
        except Exception as e:
            print(f"Error checking market status for {name}: {e}")
            statuses[name] = {"status": "UNKNOWN"}

    return statuses


def parse_market_snapshot(now: datetime = None) -> dict:
    """
    Get the market status snapshot and derive useful timing info.

    Returns a dict with:
        - any_open: bool
        - earliest_current_open: datetime | None  (earliest open time among currently-open exchanges)
        - soonest_close: datetime | None           (soonest close among currently-open exchanges)
        - latest_close: datetime | None            (latest close among currently-open exchanges)
        - earliest_next_open: datetime | None      (soonest next open across all exchanges)
    """
    if now is None:
        now = datetime.now(timezone.utc)

    statuses = get_market_status(now)
    today = now.date()

    any_open = False
    earliest_current_open: datetime | None = None
    soonest_close: datetime | None = None
    latest_close: datetime | None = None
    earliest_next_open: datetime | None = None

    for info in statuses.values():
        status = info.get("status")

        if status == "OPEN":
            any_open = True

            open_str = info.get("opened_at_utc")
            if open_str:
                h, m = map(int, open_str.split(":"))
                open_dt = datetime(
                    today.year, today.month, today.day, h, m, tzinfo=timezone.utc
                )
                if earliest_current_open is None or open_dt < earliest_current_open:
                    earliest_current_open = open_dt

            close_str = info.get("closes_at_utc")
            if close_str:
                h, m = map(int, close_str.split(":"))
                close_dt = datetime(
                    today.year, today.month, today.day, h, m, tzinfo=timezone.utc
                )
                if soonest_close is None or close_dt < soonest_close:
                    soonest_close = close_dt
                if latest_close is None or close_dt > latest_close:
                    latest_close = close_dt

        next_open_str = info.get("next_session_open_utc")
        if next_open_str:
            next_open_dt = datetime.strptime(next_open_str, "%Y-%m-%d %H:%M").replace(
                tzinfo=timezone.utc
            )
            if earliest_next_open is None or next_open_dt < earliest_next_open:
                earliest_next_open = next_open_dt

    return {
        "any_open": any_open,
        "earliest_current_open": earliest_current_open,
        "soonest_close": soonest_close,
        "latest_close": latest_close,
        "earliest_next_open": earliest_next_open,
    }
