from datetime import datetime, timezone
from typing import Any, Dict

from pydantic import BaseModel, Field

from ibkr.ibTools import IBTools
from llm.tools.base import register_tool


class CancelOrderArgs(BaseModel):
    order_id: int = Field(..., gt=0)


@register_tool(
    "cancel_order",
    description="Cancel an existing order via Interactive Brokers TWS API.",
    args_model=CancelOrderArgs,
    review=False,
)
async def cancel_order(args: Dict[str, Any]) -> Dict[str, Any]:
    a = CancelOrderArgs(**args)

    ibTools = IBTools.get_instance()

    async with ibTools.guarded():
        trade = next(
            (t for t in ibTools.ib.trades() if t.order.orderId == a.order_id), None
        )

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

        ibTools.ib.cancelOrder(trade.order)

        return {
            "status": "CANCEL_REQUESTED",
            "orderId": a.order_id,
            "currentStatus": trade.orderStatus.status,
            "asOf": datetime.now(timezone.utc).isoformat(),
        }
