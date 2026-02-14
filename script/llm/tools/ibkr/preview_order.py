from typing import Any, Dict, Literal, Optional

from ib_async import LimitOrder, MarketOrder, Stock
from pydantic import BaseModel, Field, model_validator

from ibkr.ibTools import IBTools
from logger import get_logger
from llm.tools.base import register_tool

logger = get_logger(__name__)


class PreviewOrderArgs(BaseModel):
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


@register_tool("preview_order", description="Preview a stock order via Interactive Brokers TWS API.", args_model=PreviewOrderArgs)
async def preview_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = PreviewOrderArgs(**args)
    
    contract: Stock
    if (a.primary_exchange):
        contract = Stock(a.symbol, a.exchange, a.currency, primaryExchange=a.primary_exchange)
    else:
        contract = Stock(a.symbol, a.exchange, a.currency)

    ibTools = IBTools.get_instance()

    async with ibTools.ib_sem:
        if a.order_type == "MKT":
            order = MarketOrder(a.side, a.qty)
        else:
            if a.limit_price is None:
                raise ValueError("limit_price required for LMT")
            order = LimitOrder(a.side, a.qty, a.limit_price)
        
        order.tif = "DAY"
        
        estimate = await ibTools.ib.whatIfOrderAsync(contract, order)

        logger.debug("Order estimate for %s %s %s: %s", a.side, a.qty, contract.symbol, estimate)

        return {
            "symbol": contract.symbol,
            "exchange": contract.exchange,
            "currency": contract.currency,
            "side": a.side,
            "qty": a.qty,
            "type": a.order_type,
            "status": getattr(estimate, "status", None),
            "commission": getattr(estimate, "commission", None),
            "minCommission": getattr(estimate, "minCommission", None),
            "maxCommission": getattr(estimate, "maxCommission", None),
            "initMarginChange": getattr(estimate, "initMarginChange", None),
            "maintMarginChange": getattr(estimate, "maintMarginChange", None),
            "equityWithLoanChange": getattr(estimate, "equityWithLoanChange", None),
            "warningText": getattr(estimate, "warningText", None),
            "commissionCurrency": getattr(estimate, "commissionCurrency", None),
            "completedStatus": getattr(estimate, "completedStatus", None),
        }
