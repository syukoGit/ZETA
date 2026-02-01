import asyncio
from datetime import datetime, timezone
import math
from typing import Any, Dict
from ib_async import Stock
import numpy as np
from ibkr.toolArgs import GetHistoryArgs, GetQuoteArgs, GetVolatilityMetricsArgs
from ibkr.toolRegistry import register_tool
from ibkr.ibTools import IBTools
from ibkr.utils import clean_price, clean_size


@register_tool("get_history", description="Return historical market data bars for a given symbol.", args_model=GetHistoryArgs)
async def get_history(args: Dict[str, Any]) -> Dict[str, Any]:
    a = GetHistoryArgs(**args)

    ibTools = IBTools.get_instance()

    contract = Stock(a.symbol, "SMART", "USD")

    async with ibTools.ib_sem:
        bars = await ibTools.ib.reqHistoricalDataAsync(
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

@register_tool("get_quote", description="Retrieve real-time market data quote for a given symbol.", args_model=GetQuoteArgs)
async def get_quote(args: Dict[str, Any]) -> Dict[str, Any]:
    a = GetQuoteArgs(**args)

    ibTools = IBTools.get_instance()

    contract = Stock(a.symbol, a.exchange, "USD", primaryExchange=a.primary_exchange)

    async with ibTools.ib_sem:
        ibTools.ib.reqMarketDataType(3) # Delayed data

        qualified = await ibTools.ib.qualifyContractsAsync(contract)

        if not qualified or qualified[0] is None:
            raise ValueError(f"Could not qualify contract for symbol {a.symbol}")
        
        q = qualified[0]

        try:
            tickers = await asyncio.wait_for(ibTools.ib.reqTickersAsync(q), timeout=a.timeout_s)
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

@register_tool("get_volatility_metrics", description="Retrieve volatility metrics for a given symbol.", args_model=GetVolatilityMetricsArgs)
async def get_volatility_metrics(args: Dict[str, Any]) -> Dict[str, Any]:
    a = GetVolatilityMetricsArgs(**args)

    ibTools = IBTools.get_instance()

    contract = Stock(a.symbol, a.exchange, "USD", primaryExchange=a.primary_exchange)

    async with ibTools.ib_sem:
        qualified = await ibTools.ib.qualifyContractsAsync(contract)

        if not qualified or qualified[0] is None:
            raise ValueError(f"Could not qualify contract for symbol {a.symbol}")
        
        q = qualified[0]

        bars = await ibTools.ib.reqHistoricalDataAsync(
            q,
            endDateTime="",
            durationStr=a.duration,
            barSizeSetting=a.bar_size,
            whatToShow="TRADES",
            useRTH=a.use_rth,
            formatDate=1,
        )

        if len(bars) < a.lookback_days + 1:
            raise ValueError("Not enough historical bars to compute volatility metrics")
        
        # Convert to arrays
        highs = np.array([b.high for b in bars])
        lows = np.array([b.low for b in bars])
        closes = np.array([b.close for b in bars])

        # ATR
        prev_closes = closes[:-1]
        tr = np.maximum.reduce([
            highs[1:] - lows[1:],
            np.abs(highs[1:] - prev_closes),
            np.abs(lows[1:] - prev_closes),
        ])

        atr = float(np.mean(tr[-a.lookback_days:]))

        # Realized volatility
        log_returns = np.diff(np.log(closes))
        realized_vol = float(np.std(log_returns[-a.lookback_days:]) * math.sqrt(252))

        # Range & gaps
        avg_range = float(np.mean(highs[-a.lookback_days:] - lows[-a.lookback_days:]))
        gaps = np.abs(np.diff(closes) / closes[:-1])
        avg_gap = float(np.mean(gaps[-a.lookback_days:]))

        return {
            "status": "OK",
            "symbol": a.symbol,
            "lookback_days": a.lookback_days,
            "atr": atr,
            "realized_vol": realized_vol,
            "avg_range": avg_range,
            "avg_gap_pct": avg_gap,
            "useRTH": a.use_rth,
            "asOf": datetime.now(timezone.utc).isoformat(),
        }