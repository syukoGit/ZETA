from typing import Any, Dict, Literal, Optional

from ib_async import LimitOrder, MarketOrder, Stock
from pydantic import BaseModel, Field, model_validator

from ibkr.ibTools import IBTools
from llm.tools.base import register_tool


class PlaceOrderArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    exchange: str = Field("SMART", min_length=1, description="Exchange code. Use 'SMART' for IBKR to choose the best exchange")
    currency: str = Field("USD", min_length=1)
    primary_exchange: Optional[str] = Field(None, min_length=1)

    side: Literal["BUY", "SELL"] = Field(..., description="Order side for the entry order")
    qty: float = Field(..., gt=0)

    order_type: Literal["MKT", "LMT"] = Field(..., description="Type of the order")
    limit_price: Optional[float] = None

    @model_validator(mode="after")
    def validate_logic(self):
        if self.order_type == "LMT" and self.limit_price is None:
            raise ValueError("limit_price required for LMT orders")
        return self


@register_tool("place_order", description="Place a stock order via Interactive Brokers TWS API.", args_model=PlaceOrderArgs)
async def place_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = PlaceOrderArgs(**args)

    ibTools = IBTools.get_instance()
    
    contract: Stock
    if (a.primary_exchange):
        contract = Stock(a.symbol, a.exchange, a.currency, primaryExchange=a.primary_exchange)
    else:
        contract = Stock(a.symbol, a.exchange, a.currency)

    async with ibTools.ib_sem:
        if a.order_type == "MKT":
            order = MarketOrder(a.side, a.qty)
        else:
            order = LimitOrder(a.side, a.qty, a.limit_price)
        
        if ibTools.dry_run:
            return {
                "status": "DRY_RUN",
                "symbol": contract.symbol,
                "exchange": contract.exchange,
                "currency": contract.currency,
                "side": a.side,
                "qty": a.qty,
                "type": a.order_type,
                "limitPrice": a.limit_price,
            }
        
        trade = ibTools.ib.placeOrder(contract, order)
        
        return {
            "status": "SUBMITTED",
            "orderId": trade.order.orderId,
            "symbol": contract.symbol,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "side": a.side,
            "qty": a.qty,
            "type": a.order_type,
            "limitPrice": a.limit_price,
        }