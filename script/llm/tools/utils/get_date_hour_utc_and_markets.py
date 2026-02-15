from datetime import datetime, timezone
from typing import Any, Dict

from llm.tools.base import register_tool
from utils.market_status import get_market_status


@register_tool("get_date_hour_utc_and_markets", description="Get the current UTC date/time and the open/closed status of major stock exchanges")
async def get_date_hour_utc_and_markets(_: Dict[str, Any]) -> Dict[str, str]:
    now = datetime.now(timezone.utc)

    return {
        "date_and_hour": now.strftime("%Y-%m-%d %H:%M:%S"),
        "markets": get_market_status(now),
    }