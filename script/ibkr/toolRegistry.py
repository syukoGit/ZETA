
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict

from pydantic import BaseModel

from .ibTools import IBTools
from .toolArgs import *


@dataclass
class ToolSpec:
    description: str
    args_model: type[BaseModel]
    handler: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]

def get_tools() -> Dict[str, ToolSpec]:
    ib = IBTools.get_instance()

    return {
        "get_positions": ToolSpec(
            description="Return current IB positions.",
            args_model=GetPositionsArgs,
            handler=ib.get_positions,
        ),
        "get_cash_balance": ToolSpec(
            description="Retrieve cash balance information from Interactive Brokers.",
            args_model=GetCashBalanceArgs,
            handler=ib.get_cash_balance,
        ),
        "get_open_trades": ToolSpec(
            description="Return current IB open trades.",
            args_model=GetOpenTradesArgs,
            handler=ib.get_open_trades,
        ),
        "get_trade_history": ToolSpec(
            description="Return trade history for this session.",
            args_model=GetTradeHistoryArgs,
            handler=ib.get_trade_history,
        ),
        "get_pnl": ToolSpec(
            description="Get the profit and loss (PnL) for the positions.",
            args_model=GetPnlArgs,
            handler=ib.get_pnl,
        ),
        "get_history": ToolSpec(
            description="Return historical bars for a US stock.",
            args_model=GetHistoryArgs,
            handler=ib.get_history,
        ),
        "place_order": ToolSpec(
            description="Place a stock order via Interactive Brokers TWS API.",
            args_model=PlaceOrderArgs,
            handler=ib.place_order,
        ),
    }