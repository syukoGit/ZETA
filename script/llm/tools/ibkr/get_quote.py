import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ib_async import Stock, Ticker
from pydantic import BaseModel, Field

from ibkr.ibTools import IBTools
from ibkr.utils import clean_price, clean_size
from llm.tools.base import register_tool
from logger import get_logger

logger = get_logger(__name__)

# Fallback chain: requested type → delayed → delayed-frozen
_FALLBACK_DATA_TYPES: Dict[int, List[int]] = {
    1: [3, 4],  # real-time → delayed → delayed-frozen
    2: [4, 3],  # frozen → delayed-frozen → delayed
    3: [4],     # delayed → delayed-frozen
    4: [3],     # delayed-frozen → delayed
}

MIN_TIMEOUT_S = 14.0


class GetQuoteArgs(BaseModel):
    symbol: str = Field(..., min_length=1, description="Ticker")
    currency: str = Field("USD", min_length=1, description="Currency code")
    exchange: str = Field("SMART", min_length=1, description="Exchange code. Use 'SMART' for IBKR to choose the best exchange")
    primary_exchange: Optional[str] = Field(None, description="Optional primary exchange")
    timeout_s: float = Field(30.0, gt=MIN_TIMEOUT_S, description="Timeout for quote fetch (clamped to 15s minimum)")
    market_data_type: int = Field(3, description="IB market data type (1=real-time, 2=frozen, 3=delayed, 4=delayed-frozen). Default 3 (delayed) for reliability.")
    regulatory_snapshot: bool = Field(False)


async def _request_snapshot(
    ib, contract, timeout_s: float, regulatory_snapshot: bool
) -> Optional[Ticker]:
    """Request a single market-data snapshot with timeout. Returns Ticker or None."""
    try:
        tickers = await asyncio.wait_for(
            ib.reqTickersAsync(contract, regulatorySnapshot=regulatory_snapshot),
            timeout=timeout_s,
        )
        if tickers:
            t = tickers[0]
            # Check if we actually got meaningful data (not all NaN/-1)
            has_data = any(
                clean_price(getattr(t, f, None)) is not None
                for f in ("bid", "ask", "last", "close")
            )
            if has_data:
                return t
            logger.warning("Ticker returned but no meaningful price fields for contract %s", contract.symbol)
            return None
        return None
    except asyncio.TimeoutError:
        logger.warning("reqTickersAsync timed out after %.1fs for %s", timeout_s, contract.symbol)
        return None


@register_tool("get_quote", description="Retrieve market data quote for a given symbol. Uses automatic fallback across market data types if the requested type times out.", args_model=GetQuoteArgs)
async def get_quote(args: Dict[str, Any]) -> Dict[str, Any]:
    a = GetQuoteArgs(**args)

    # Clamp timeout to a safe minimum
    effective_timeout = max(a.timeout_s, MIN_TIMEOUT_S)

    ibTools = IBTools.get_instance()
    ib = ibTools.ib

    contract: Stock
    if a.primary_exchange:
        contract = Stock(a.symbol, a.exchange, a.currency, primaryExchange=a.primary_exchange)
    else:
        contract = Stock(a.symbol, a.exchange, a.currency)

    async with ibTools.ib_sem:
        # --- Qualify contract (outside the retry loop, only needed once) ---
        qualified = await ib.qualifyContractsAsync(contract)
        if not qualified or qualified[0] is None:
            raise ValueError(f"Could not qualify contract for symbol {a.symbol}")
        q = qualified[0]

        # --- Build the ordered list of market_data_types to try ---
        types_to_try = [a.market_data_type] + _FALLBACK_DATA_TYPES.get(a.market_data_type, [])

        last_error: Optional[str] = None
        used_data_type: Optional[int] = None

        for mdt in types_to_try:
            logger.info(
                "get_quote %s: trying market_data_type=%d, timeout=%.1fs",
                a.symbol, mdt, effective_timeout,
            )
            ib.reqMarketDataType(mdt)

            try:
                t = await _request_snapshot(ib, q, effective_timeout, a.regulatory_snapshot)
            except Exception as e:
                last_error = str(e)
                logger.error("get_quote %s error with mdt=%d: %s", a.symbol, mdt, last_error)
                continue

            if t is not None:
                used_data_type = mdt
                break
        else:
            # All attempts exhausted
            logger.warning("get_quote %s: all market_data_types exhausted, returning TIMEOUT", a.symbol)
            return {
                "status": "TIMEOUT",
                "asOf": datetime.now(timezone.utc).isoformat(),
                "symbol": a.symbol,
                "conId": getattr(q, "conId", None),
                "timeout_s": effective_timeout,
                "tried_data_types": types_to_try,
                "last_error": last_error,
            }

        # --- Format the successful response ---
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
            "marketDataType": used_data_type,
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