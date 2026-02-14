from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
import uuid

from ib_async import LimitOrder, MarketOrder, Stock, StopOrder
from pydantic import BaseModel, Field, model_validator

from ibkr.ibTools import IBTools
from llm.tools.base import register_tool


class PlaceBracketOrderArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    exchange: str = Field("SMART", min_length=1, description="Exchange code. Use 'SMART' for IBKR to choose the best exchange")
    currency: str = Field("USD", min_length=1)
    primary_exchange: Optional[str] = None

    # Parent
    side: Literal["BUY", "SELL"] = Field(..., description="Order side for the entry order")
    qty: int = Field(..., gt=0)
    entry_type: Literal["MKT", "LMT"] = Field(..., description="Type of the entry order")
    entry_limit_price: Optional[float] = Field(None, gt=0)

    # Take profit
    take_profit_price: float = Field(..., gt=0)

    # Stop loss
    stop_loss_price: float = Field(..., gt=0)

    # Time in force
    tif: Literal["DAY", "GTC"] = Field("DAY", description="Time in force for the orders")

    @model_validator(mode="after")
    def validate_prices(self):
        if self.side == "BUY":
            if not (self.stop_loss_price < self.take_profit_price):
                raise ValueError("BUY: stop_loss must be < take_profit")
        else:
            if not (self.stop_loss_price > self.take_profit_price):
                raise ValueError("SELL: stop_loss must be > take_profit")

        return self


# @register_tool("place_bracket_order", description="Place a bracket order via Interactive Brokers TWS API.", args_model=PlaceBracketOrderArgs)
async def place_bracket_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = PlaceBracketOrderArgs(**args)

    ibTools = IBTools.get_instance()

    contract: Stock
    if (a.primary_exchange):
        contract = Stock(a.symbol, a.exchange, a.currency, primaryExchange=a.primary_exchange)
    else:
        contract = Stock(a.symbol, a.exchange, a.currency)

    async with ibTools.ib_sem:
        await ibTools.ib.qualifyContractsAsync(contract)

        oca_group = f"OCA-{uuid.uuid4().hex[:10]}"

        # Parent order
        if a.entry_type == "MKT":
            parent = MarketOrder(a.side, a.qty)
        else:
            parent = LimitOrder(a.side, a.qty, a.entry_limit_price)
        
        parent.tif = a.tif
        parent.transmit = False

        # Take Profit order
        tp = LimitOrder(
            "SELL" if a.side == "BUY" else "BUY",
            a.qty,
            a.take_profit_price,
        )

        tp.parentId = parent.orderId
        tp.ocaGroup = oca_group
        tp.ocaType = 1
        tp.transmit = False

        # Stop Loss order
        sl = StopOrder(
            "SELL" if a.side == "BUY" else "BUY",
            a.qty,
            a.stop_loss_price,
        )
        sl.parentId = parent.orderId
        sl.ocaGroup = oca_group
        sl.ocaType = 1
        sl.transmit = True

        if ibTools.dry_run:
            return {
                "status": "DRY_RUN",
                "symbol": a.symbol,
                "qty": a.qty,
                "entry": a.entry_type,
                "tp": a.take_profit_price,
                "sl": a.stop_loss_price,
            }
        
        parent_trade = ibTools.ib.placeOrder(contract, parent)
        ibTools.ib.placeOrder(contract, tp)
        ibTools.ib.placeOrder(contract, sl)

        return {
            "status": "SUBMITTED",
            "symbol": a.symbol,
            "side": a.side,
            "qty": a.qty,
            "ocaGroup": oca_group,
            "parentOrderId": parent_trade.order.orderId,
            "asOf": datetime.now(timezone.utc).isoformat(),
        }
