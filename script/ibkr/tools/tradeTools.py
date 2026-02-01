from typing import Any, Dict
from ibkr.utils import format_trades
from ibkr.toolRegistry import register_tool
from ibkr.ibTools import IBTools

@register_tool("get_open_trades", description="Return current IB open trades.")
async def get_open_trades(_: Dict[str, Any]) -> Dict[str, Any]:
    ibTools = IBTools.get_instance()

    trades = ibTools.ib.openTrades()
    return {"open_trades": format_trades(trades) if trades else []}

@register_tool("get_trade_history", description="Return trade history for this session.")
async def get_trade_history(_: Dict[str, Any]) -> Dict[str, Any]:
    ibTools = IBTools.get_instance()

    trades = ibTools.ib.trades()
    return {"trade_history": format_trades(trades) if trades else []}