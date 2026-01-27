import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from ib_async import IB, LimitOrder, MarketOrder, Stock, Trade

from ibkr.toolArgs import *
from ibkr.utils import clean_price, clean_size, format_trades

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

    def __new__(cls, ib: IB, *, ib_sem: asyncio.Semaphore, dry_run: bool = True):
        if cls._instance is None:
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
            pos: list[Dict[str, Any]] = [
                {"symbol": p.contract.symbol, "position": p.position, "avgCost": p.avgCost}
                for p in self.ib.positions()
            ]
        return {"positions": pos}
    
    async def get_cash_balance(self, _: Dict[str, Any]) -> Dict[str, Any]:
        async with self.ib_sem:
            account_values = await self.ib.accountSummaryAsync()
            cash_values: list[Dict[str, Any]] = [
                {
                    "currency": av.currency,
                    "value": float(av.value),
                }
                for av in account_values
                if av.tag == "CashBalance"
            ]
        return {"cash_balances": cash_values}
    
    async def get_open_trades(self, _: Dict[str, Any]) -> Dict[str, Any]:
        trades = self.ib.openTrades()
        return {"open_trades": format_trades(trades) if trades else []}
    
    async def get_trade_history(self, _: Dict[str, Any]) -> Dict[str, Any]:
        trades = self.ib.trades()
        return {"trade_history": format_trades(trades) if trades else []}
    async def get_pnl(self, _: Dict[str, Any]) -> Dict[str, Any]:
        async with self.ib_sem:
            portfolio = self.ib.portfolio()
            pnl_values: list[Dict[str, Any]] = [
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
        
        out: list[Dict[str, Any]] = [{
            "time": b.date.isoformat(), "open": float(b.open), "high": float(b.high),
            "low": float(b.low), "close": float(b.close), "volume": float(b.volume)
        } for b in bars]

        return {"symbol": a.symbol, "bars": out}

    async def place_order(self, args: Dict[str, Any]) -> Dict[str, Any]:
        a = PlaceOrderArgs(**args)
        
        contract = Stock(a.symbol, "SMART", "USD", primaryExchange="NASDAQ")

        async with self.ib_sem:
            if a.order_type == "MKT":
                order = MarketOrder(a.side, a.qty)
            else:
                if a.limit_price is None:
                    raise ValueError("limit_price required for LMT")
                order = LimitOrder(a.side, a.qty, a.limit_price)
            
            if self.dry_run:
                return {"status": "DRY_RUN", "symbol": a.symbol, "side": a.side, "qty": a.qty, "type": a.order_type}
            
            trade = self.ib.placeOrder(contract, order)
            
            return {"status": "SUBMITTED", "orderId": trade.order.orderId}

    async def get_quote(self, args: Dict[str, Any]) -> Dict[str, Any]:
        a = GetQuoteArgs(**args)

        contract = Stock(a.symbol, a.exchange, "USD", primaryExchange=a.primary_exchange)

        async with self.ib_sem:
            self.ib.reqMarketDataType(3) # Delayed data

            qualified = await self.ib.qualifyContractsAsync(contract)

            if not qualified or qualified[0] is None:
                raise ValueError(f"Could not qualify contract for symbol {a.symbol}")
            
            q = qualified[0]

            try:
                tickers = await asyncio.wait_for(self.ib.reqTickersAsync(q), timeout=a.timeout_s)
            except asyncio.TimeoutError:
                return {
                    "status": "TIMEOUT",
                    "asOf": datetime.now(timezone.utc).isoformat(),
                    "symbol": a.symbol,
                    "conId": getattr(q, "conId", None),
                    "timeout_s": a.timeout_s,
                }
            except Exception as e:
                return {
                    "status": "ERROR",
                    "error": str(e),
                    "asOf": datetime.now(timezone.utc).isoformat(),
                    "symbol": a.symbol,
                    "conId": getattr(q, "conId", None),
                }
            
            if not tickers:
                return {
                    "status": "NO_DATA",
                    "asOf": datetime.now(timezone.utc).isoformat(),
                    "symbol": a.symbol,
                    "conId": getattr(q, "conId", None),
                }
            
            t = tickers[0]

            bid = clean_price(getattr(t, "bid", None))
            ask = clean_price(getattr(t, "ask", None))
            last = clean_price(getattr(t, "last", None))
            close = clean_price(getattr(t, "close", None))
            open_ = clean_price(getattr(t, "open", None))
            high = clean_price(getattr(t, "high", None))
            low = clean_price(getattr(t, "low", None))
            vwap = clean_price(getattr(t, "vwap", None))
            volume = clean_size(getattr(t, "volume", None))

            mid = None
            if bid is not None and ask is not None and ask >= bid:
                mid = (bid + ask) / 2.0

            spread = None
            if bid is not None and ask is not None and ask >= bid:
                spread = ask - bid
            
            return {
                "status": "OK",
                "asOf": datetime.now(timezone.utc).isoformat(),
                "symbol": a.symbol,
                "conId": getattr(q, "conId", None),
                "exchange": getattr(q, "exchange", a.exchange),
                "primaryExchange": getattr(q, "primaryExchange", a.primary_exchange),
                "currency": getattr(q, "currency", a.currency),
                "regulatorySnapshot": a.regulatory_snapshot,
                "bid": bid,
                "ask": ask,
                "mid": mid,
                "spread": spread,
                "last": last,
                "close": close,
                "open": open_,
                "high": high,
                "low": low,
                "vwap": vwap,
                "volume": volume,
                "halted": getattr(t, "halted", None),
            }
    
    async def preview_order(self, args: Dict[str, Any]) -> Dict[str, Any]:
        a = PlaceOrderArgs(**args)
        
        contract = Stock(a.symbol, "SMART", "USD", primaryExchange="NASDAQ")

        async with self.ib_sem:
            if a.order_type == "MKT":
                order = MarketOrder(a.side, a.qty)
            else:
                if a.limit_price is None:
                    raise ValueError("limit_price required for LMT")
                order = LimitOrder(a.side, a.qty, a.limit_price)
            
            order.tif = "DAY"
            
            estimate = await self.ib.whatIfOrderAsync(contract, order)

            print(estimate)

            return {
                "symbol": a.symbol,
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