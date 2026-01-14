
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
        "get_orders": ToolSpec(
            description="Return current IB orders.",
            args_model=GetOrdersArgs,
            handler=ib.get_orders,
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