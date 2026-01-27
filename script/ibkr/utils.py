from typing import Any, Dict, Optional
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

def format_trades(trades: list[Trade]) -> list[Dict[str, Any]]:
    return [
        {
            "symbol": trade.contract.symbol,
            "orderId": trade.order.orderId,
            "action": trade.order.action,
            "totalQuantity": trade.order.totalQuantity,
            "orderType": trade.order.orderType,
            "lmtPrice": float(trade.order.lmtPrice) if trade.order.lmtPrice not in (None, 0) else None,
            "status": trade.orderStatus.status,
            "filled": trade.orderStatus.filled,
            "remaining": trade.orderStatus.remaining,
        }
        for trade in trades
    ]