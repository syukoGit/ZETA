import asyncio
from typing import Any, Dict, Optional
from ib_async import IB, LimitOrder, MarketOrder, Stock

from ibkr.toolArgs import *

async def init_ib_connection(dry_run: bool = True) -> IB:
    ib = IB()
    await ib.connectAsync("127.0.0.1", 7497, clientId=0)

    while not ib.isConnected():
        await asyncio.sleep(0.1)

    ib_sem = asyncio.Semaphore(1)

    _ = IBTools(ib, ib_sem=ib_sem, dry_run=dry_run)

    return ib

class IBTools:
    _instance: Optional["IBTools"] = None

    ib: IB
    ib_sem: asyncio.Semaphore
    dry_run: bool

    def __new__(cls, ib: IB = None, *, ib_sem: asyncio.Semaphore = None, dry_run: bool = True):
        if cls._instance is None:
            if ib is None or ib_sem is None:
                raise ValueError("ib and ib_sem are required for first instantiation")
            cls._instance = super().__new__(cls)
            cls._instance.ib = ib
            cls._instance.ib_sem = ib_sem
            cls._instance.dry_run = dry_run
        return cls._instance

    @classmethod
    def get_instance(cls) -> "IBTools":
        if cls._instance is None:
            raise RuntimeError("IBTools has not been initialized. Call IBTools(ib, ib_sem=...) first.")
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance (useful for testing)."""
        cls._instance = None

    async def get_positions(self, _: Dict[str, Any]) -> Dict[str, Any]:
        async with self.ib_sem:
            pos = [
                {"symbol": p.contract.symbol, "position": p.position, "avgCost": p.avgCost}
                for p in self.ib.positions()
            ]
        return {"positions": pos}
    
    async def get_cash_balance(self, _: Dict[str, Any]) -> Dict[str, Any]:
        async with self.ib_sem:
            account_values = await self.ib.accountSummaryAsync()
            cash_values = [
                {
                    "currency": av.currency,
                    "value": float(av.value),
                }
                for av in account_values
                if av.tag == "CashBalance"
            ]
        return {"cash_balances": cash_values}
    
    async def get_orders(self, _: Dict[str, Any]) -> Dict[str, Any]:
        trades = self.ib.openTrades()
        if not trades:
            return {"orders": []}
        
        outputs = []
        
        for trade in trades:
            order = trade.order
            status = trade.orderStatus
            contract = trade.contract

            outputs.append({
                "symbol": contract.symbol,
                "orderId": order.orderId,
                "action": order.action,
                "totalQuantity": order.totalQuantity,
                "orderType": order.orderType,
                "lmtPrice": float(order.lmtPrice) if order.lmtPrice not in (None, 0) else None,
                "status": status.status,
                "filled": status.filled,
                "remaining": status.remaining,
            })

        return {"orders": outputs}

    async def get_pnl(self, _: Dict[str, Any]) -> Dict[str, Any]:
        async with self.ib_sem:
            portfolio = self.ib.portfolio()
            pnl_values = [
                {
                    "currency": av.contract.currency,
                    "symbol": av.contract.symbol,
                    "position": av.position,
                    "averageCost": float(av.averageCost),
                    "marketValue": float(av.marketValue),
                    "marketPrice": float(av.marketPrice),
                    "unrealizedPnL": float(av.unrealizedPNL),
                    "realizedPnL": float(av.realizedPNL),
                }
                for av in portfolio
            ]
        return {"pnl": pnl_values}

    async def get_history(self, args: Dict[str, Any]) -> Dict[str, Any]:
        a = GetHistoryArgs(**args)

        contract = Stock(a.symbol, "SMART", "USD")

        async with self.ib_sem:
            bars = await self.ib.reqHistoricalDataAsync(
                contract,
                endDateTime="",
                durationStr=a.duration,
                barSizeSetting=a.bar_size,
                whatToShow="TRADES",
                useRTH=a.use_rth,
                formatDate=1,
                keepUpToDate=False,
            )
        
        out = [{
            "time": b.date.isoformat(), "open": float(b.open), "high": float(b.high),
            "low": float(b.low), "close": float(b.close), "volume": float(b.volume)
        } for b in bars]

        return {"symbol": a.symbol, "bars": out}

    async def place_order(self, args: Dict[str, Any]) -> Dict[str, Any]:
        a = PlaceOrderArgs(**args)

        if a.order_type == "LMT" and a.limit_price is None:
            raise ValueError("limit_price required for LMT")
        
        contract = Stock(a.symbol, "SMART", "USD", primaryExchange="NASDAQ")

        async with self.ib_sem:
            if a.order_type == "MKT":
                order = MarketOrder(a.side, a.qty)
            else:
                order = LimitOrder(a.side, a.qty, a.limit_price)
            
            if self.dry_run:
                return {"status": "DRY_RUN", "symbol": a.symbol, "side": a.side, "qty": a.qty, "type": a.order_type}
            
            trade = self.ib.placeOrder(contract, order)
            
            return {"status": "SUBMITTED", "orderId": trade.order.orderId}