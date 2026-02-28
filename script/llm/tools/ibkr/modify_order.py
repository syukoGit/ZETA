from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ibkr.ibTools import IBTools
from llm.tools.base import register_tool


class ModifyOrderArgs(BaseModel):
    order_id: int = Field(..., gt=0)
    new_limit_price: Optional[float] = Field(None, gt=0)
    new_qty: Optional[int] = Field(None, gt=0)
    time_in_force: Optional[str] = None


@register_tool("modify_order", description="Modify an existing order via Interactive Brokers TWS API.", args_model=ModifyOrderArgs, performance_review=False)
async def modify_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = ModifyOrderArgs(**args)

    ibTools = IBTools.get_instance()

    async with ibTools.ib_sem:
        trade = next((t for t in ibTools.ib.trades() if t.order.orderId == a.order_id), None)

        if trade is None:
            return {
                "status": "NOT_FOUND",
                "orderId": a.order_id,
                "asOf": datetime.now(timezone.utc).isoformat(),
            }
        
        if trade.orderStatus.status in ("Filled", "Cancelled"):
            return {
                "status": "NO_ACTION",
                "orderId": a.order_id,
                "orderStatus": trade.orderStatus.status,
                "asOf": datetime.now(timezone.utc).isoformat(),
            }
        
        if a.new_limit_price is not None:
            trade.order.lmtPrice = a.new_limit_price
        if a.new_qty is not None:
            trade.order.totalQuantity = a.new_qty
        if a.time_in_force is not None:
            trade.order.tif = a.time_in_force
        
        ibTools.ib.placeOrder(trade.contract, trade.order)

        return {
            "status": "MODIFY_REQUESTED",
            "orderId": a.order_id,
            "currentStatus": trade.orderStatus.status,
            "asOf": datetime.now(timezone.utc).isoformat(),
        }
