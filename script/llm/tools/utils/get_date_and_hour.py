from datetime import datetime, timezone
from typing import Any, Dict

from llm.tools.base import register_tool

@register_tool("get_date_and_hour_utc", description="Get the current date and hour in the format 'YYYY-MM-DD HH:MM:SS'.")
async def get_date_and_hour_utc(_: Dict[str, Any]) -> Dict[str, str]:
    """
    Get the current date and hour.
    
    Returns:
        dict: A dictionary containing the current date and hour in the format "YYYY-MM-DD HH:MM:SS".
    """
    now = datetime.now(timezone.utc)
    date_and_hour = now.strftime("%Y-%m-%d %H:%M:%S")
    return {"date_and_hour": date_and_hour}