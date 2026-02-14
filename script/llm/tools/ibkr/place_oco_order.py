from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
import uuid

from ib_async import LimitOrder, Stock, StopOrder
from pydantic import BaseModel, Field, model_validator

from ibkr.ibTools import IBTools
from llm.tools.base import register_tool


class PlaceOcoOrderArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    exchange: str = Field("SMART", min_length=1, description="Exchange code. Use 'SMART' for IBKR to choose the best exchange")
    currency: str = Field("USD", min_length=1)
    primary_exchange: Optional[str] = Field(None, min_length=1)

    # Position
    side: Literal["BUY", "SELL"] = Field(..., description="Order side for the entry order")
    qty: int = Field(..., gt=0)

    # Take Profit
    take_profit_price: float = Field(..., gt=0)

    # Stop Loss
    stop_loss_price: float = Field(..., gt=0)

    tif: Literal["DAY", "GTC"] = Field("DAY", description="Time in force for the orders")

    @model_validator(mode="after")
    def validate_logic(self):
        # SELL
        if self.side == "SELL":
            if not self.stop_loss_price < self.take_profit_price:
                raise ValueError("SELL OCO: stop_loss < take_profit required")
        # BUY
        else:
            if not self.stop_loss_price > self.take_profit_price:
                raise ValueError("BUY OCO: stop_loss > take_profit required")
        return self


# @register_tool("place_oco_order", description="Place an OCO (One-Cancels-the-Other) order via Interactive Brokers TWS API.", args_model=PlaceOcoOrderArgs)
async def place_oco_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = PlaceOcoOrderArgs(**args)

    ibTools = IBTools.get_instance()

    contract: Stock
    if (a.primary_exchange):
        contract = Stock(a.symbol, a.exchange, a.currency, primaryExchange=a.primary_exchange)
    else:
        contract = Stock(a.symbol, a.exchange, a.currency)

    async with ibTools.ib_sem:
        await ibTools.ib.qualifyContractsAsync(contract)

        oca_group = f"OCA-{uuid.uuid4().hex[:10]}"

        # Take Profit order
        tp = LimitOrder(
            a.side,
            a.qty,
            a.take_profit_price,
        )
        tp.tif = a.tif
        tp.ocaGroup = oca_group
        tp.ocaType = 1
        tp.transmit = False

        # Stop Loss order
        sl = StopOrder(
            a.side,
            a.qty,
            a.stop_loss_price,
        )
        sl.tif = a.tif
        sl.ocaGroup = oca_group
        sl.ocaType = 1
        sl.transmit = True

        tp_trade = ibTools.ib.placeOrder(contract, tp)
        sl_trade = ibTools.ib.placeOrder(contract, sl)

        return {
            "status": "SUBMITTED",
            "symbol": contract.symbol,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "side": a.side,
            "qty": a.qty,
            "ocaGroup": oca_group,
            "takeProfitOrderId": tp_trade.order.orderId,
            "stopLossOrderId": sl_trade.order.orderId,
            "asOf": datetime.now(timezone.utc).isoformat(),
        }
