import asyncio
from typing import Any, Dict, Optional, Tuple
from ib_async import Trade


def clean_price(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except Exception:
        return None
    # ib_async default emptyPrice is typically -1; also guard NaN
    if v != v or v <= -0.5:  # NaN or sentinel
        return None
    return v


def clean_size(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        v = float(x)
    except Exception:
        return None
    if v != v or v < 0:
        return None
    return v


async def wait_order_confirmed(
    trade: Trade, timeout: float = 10.0
) -> Tuple[str, Optional[str]]:
    """
    Wait until the order leaves the pending states (PendingSubmit, PreSubmitted)
    and reaches either an active state (Submitted) or a terminal state
    (Filled, Cancelled, ApiCancelled, Inactive).

    Returns:
        (status, error_message) where error_message is None if the order is
        working normally, or the last log message if the order is terminal.
        If the timeout expires before confirmation, returns ("PENDING", None).
    """
    loop = asyncio.get_event_loop()
    future: asyncio.Future[None] = loop.create_future()

    def on_status(t: Trade) -> None:
        if not future.done() and (t.isDone() or t.isWorking()):
            future.set_result(None)

    trade.statusEvent += on_status

    # Already in a final/working state before we even subscribed
    if trade.isDone() or trade.isWorking():
        future.set_result(None)

    try:
        await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
    except asyncio.TimeoutError:
        return ("PENDING", None)
    finally:
        trade.statusEvent -= on_status

    status = trade.orderStatus.status
    error: Optional[str] = None
    if trade.isDone() and trade.log:
        last = trade.log[-1]
        if last.message:
            error = last.message
    return (status, error)


def format_trades(trades: list[Trade]) -> list[Dict[str, Any]]:
    return [
        {
            "symbol": trade.contract.symbol,
            "orderId": trade.order.orderId,
            "action": trade.order.action,
            "totalQuantity": trade.order.totalQuantity,
            "orderType": trade.order.orderType,
            "lmtPrice": (
                float(trade.order.lmtPrice)
                if trade.order.lmtPrice not in (None, 0)
                else None
            ),
            "status": trade.orderStatus.status,
            "filled": trade.orderStatus.filled,
            "remaining": trade.orderStatus.remaining,
        }
        for trade in trades
    ]
