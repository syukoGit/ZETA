from typing import Any, Dict, Literal, Optional

from ib_async import LimitOrder, MarketOrder
from pydantic import BaseModel, Field, model_validator

from ibkr.contracts import qualify_contract
from ibkr.ibTools import IBTools
from llm.tools.base import register_tool
from logger import get_logger

logger = get_logger(__name__)

class PlaceOrderArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    exchange: str = Field("SMART", min_length=1, description="Exchange code. Use 'SMART' for IBKR to choose the best exchange")
    currency: str = Field("USD", min_length=1)

    side: Literal["BUY", "SELL"] = Field(..., description="Order side for the entry order")
    qty: float = Field(..., gt=0)

    order_type: Literal["MKT", "LMT"] = Field(..., description="Type of the order")
    limit_price: Optional[float] = None

    @model_validator(mode="after")
    def validate_logic(self):
        if self.order_type == "LMT" and self.limit_price is None:
            raise ValueError("limit_price required for LMT orders")
        return self


@register_tool("place_order", description="Place a stock order via Interactive Brokers TWS API.", args_model=PlaceOrderArgs, review=False)
async def place_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = PlaceOrderArgs(**args)

    ibTools = IBTools.get_instance()
    logger.info("Placing order: %s %s %s %s at %s", a.side, a.qty, a.symbol, a.exchange, a.limit_price if a.order_type == "LMT" else "MKT")

    async with ibTools.ib_sem:
        q, resolved_sec_type = await qualify_contract(
            ibTools.ib,
            {
                "symbol": a.symbol,
                "exchange": a.exchange,
                "currency": a.currency,
                "sec_type": "STK",
            }
        )

        if resolved_sec_type != "STK":
            raise ValueError(f"Unsupported security type for trading: {resolved_sec_type}. Only STK is supported.")

        if a.order_type == "MKT":
            order = MarketOrder(a.side, a.qty)
        else:
            order = LimitOrder(a.side, a.qty, a.limit_price)
        
        if ibTools.dry_run:
            return {
                "status": "DRY_RUN",
                "symbol": q.symbol,
                "exchange": q.exchange,
                "currency": q.currency,
                "side": a.side,
                "qty": a.qty,
                "type": a.order_type,
                "limitPrice": a.limit_price,
            }
        
        trade = ibTools.ib.placeOrder(q, order)
        
        return {
            "status": "SUBMITTED",
            "orderId": trade.order.orderId,
            "symbol": trade.contract.symbol,
            "exchange": trade.contract.exchange,
            "currency": trade.contract.currency,
            "side": trade.order.action,
            "qty": trade.order.totalQuantity,
            "type": trade.order.orderType,
            "limitPrice": getattr(trade.order, "lmtPrice", None),
        }