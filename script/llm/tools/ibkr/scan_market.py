from typing import Any, Dict

from ibkr.scanner.core import run_market_scan
from llm.tools.base import register_tool


@register_tool(
    "scan_market",
    description=(
        "Run the composite market scanner. Returns the top-N tickers scored "
        "across multiple IBKR scans for the current phase. Call this at the "
        "start of each run to discover opportunities."
    ),
    review=False,
)
async def scan_market(_: Dict[str, Any]) -> Dict[str, Any]:
    return await run_market_scan()
