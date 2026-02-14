from typing import Any, Dict

from ibkr.ibTools import IBTools
from ibkr.utils import format_trades
from llm.tools.base import register_tool


@register_tool("get_trade_history", description="Return trade history for this session.")
async def get_trade_history(_: Dict[str, Any]) -> Dict[str, Any]:
    ibTools = IBTools.get_instance()

    trades = ibTools.ib.trades()
    return {"trade_history": format_trades(trades) if trades else []}