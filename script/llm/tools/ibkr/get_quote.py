import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ib_async import IB, Ticker
from pydantic import BaseModel, Field

from ibkr.ibTools import IBTools
from ibkr.contracts import qualify_contract
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

def _get_data_type_name(mdt: int) -> str:
    return {
        1: "REAL-TIME",
        2: "FROZEN",
        3: "DELAYED",
        4: "DELAYED-FROZEN",
    }.get(mdt, f"UNKNOWN({mdt})")

class GetQuoteArgs(BaseModel):
    symbol: str = Field(..., min_length=1, description="Ticker")
    sec_type: Optional[str] = Field(None, description="IB contract type: STK (stock/ETF) or IND (index). If omitted, auto-detection is attempted.")
    currency: str = Field("USD", min_length=1, description="Currency code")
    exchange: str = Field("SMART", min_length=1, description="Exchange code. Use 'SMART' for stocks. For indices, provide the listing exchange (e.g. CBOE for VIX).")
    timeout_s: float = Field(30.0, gt=MIN_TIMEOUT_S, description="Timeout for quote fetch (clamped to 15s minimum)")
    market_data_type: int = Field(1, description="IB market data type (1=real-time, 2=frozen, 3=delayed, 4=delayed-frozen). Default 3 (delayed) for reliability.")
    regulatory_snapshot: bool = Field(False)


async def _request_snapshot(
    ib: IB, contract, timeout_s: float, regulatory_snapshot: bool
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


@register_tool("get_quote", description="Retrieve market data quote for a given contract. Uses automatic fallback across market data types if the requested type times out.", args_model=GetQuoteArgs)
async def get_quote(args: Dict[str, Any]) -> Dict[str, Any]:
    a = GetQuoteArgs(**args)

    # Clamp timeout to a safe minimum
    effective_timeout = max(a.timeout_s, MIN_TIMEOUT_S)

    ibTools = IBTools.get_instance()
    ib = ibTools.ib


    async with ibTools.ib_sem:
        q, resolved_sec_type = await qualify_contract(
            ib,
            {
                "symbol": a.symbol,
                "sec_type": a.sec_type,
                "exchange": a.exchange,
                "currency": a.currency,
            },
        )

        # --- Build the ordered list of market_data_types to try ---
        types_to_try = [a.market_data_type] + _FALLBACK_DATA_TYPES.get(a.market_data_type, [])

        last_error: Optional[str] = None
        used_data_type: Optional[int] = None

        for mdt in types_to_try:
            logger.debug(
                "get_quote %s: trying market_data_type=%d, timeout=%.1fs",
                a.symbol, mdt, effective_timeout,
            )
            ib.reqMarketDataType(mdt)

            try:
                t = await _request_snapshot(ibTools.ib, q, effective_timeout, a.regulatory_snapshot)
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
                "symbol": getattr(q, "symbol", a.symbol),
                "conId": getattr(q, "conId", None),
                "secType": resolved_sec_type,
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
            "secType": resolved_sec_type,
            "exchange": getattr(q, "exchange", a.exchange),
            "primaryExchange": getattr(q, "primaryExchange", None),
            "currency": getattr(q, "currency", a.currency),
            "marketDataType": _get_data_type_name(used_data_type) if used_data_type else None,
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