import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from ib_async import Stock
from pydantic import BaseModel, Field

from ibkr.ibTools import IBTools
from ibkr.utils import clean_price, clean_size
from llm.tools.base import register_tool


class GetQuoteArgs(BaseModel):
    symbol: str = Field(..., min_length=1, description="Ticker")
    currency: str = Field("USD", min_length=1, description="Currency code")
    exchange: str = Field("SMART", min_length=1, description="Exchange code. Use 'SMART' for IBKR to choose the best exchange")
    primary_exchange: Optional[str] = Field(None, description="Optional primary exchange")
    timeout_s: float = Field(6.0, gt=0, description="Timeout for quote fetch")
    # market_data_type: int = Field(..., description="IB market data type (1=real-time, 2= frozen, 3=delayed, 4=delayed-frozen)")
    regulatory_snapshot: bool = Field(False)


@register_tool("get_quote", description="Retrieve real-time market data quote for a given symbol.", args_model=GetQuoteArgs)
async def get_quote(args: Dict[str, Any]) -> Dict[str, Any]:
    a = GetQuoteArgs(**args)

    ibTools = IBTools.get_instance()

    contract: Stock
    if (a.primary_exchange):
        contract = Stock(a.symbol, a.exchange, a.currency, primaryExchange=a.primary_exchange)
    else:
        contract = Stock(a.symbol, a.exchange, a.currency)

    async with ibTools.ib_sem:
        ibTools.ib.reqMarketDataType(3) # Use the specified market data type

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
            "symbol": q.symbol,
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