from typing import Any, Dict

from ibkr.ibTools import IBTools
from ibkr.utils import format_trades
from llm.tools.base import register_tool


@register_tool("get_open_trades", description="Return current IB open trades.")
async def get_open_trades(_: Dict[str, Any]) -> Dict[str, Any]:
    ibTools = IBTools.get_instance()

    trades = ibTools.ib.openTrades()
    return {"open_trades": format_trades(trades) if trades else []}