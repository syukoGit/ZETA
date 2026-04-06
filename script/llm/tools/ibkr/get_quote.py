from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ibkr.ibTools import IBTools
from ibkr.contracts import qualify_contract
from ibkr.quotes import _FALLBACK_DATA_TYPES, _get_data_type_name, _request_snapshot
from ibkr.utils import clean_price, clean_size
from llm.tools.base import register_tool
from logger import get_logger

logger = get_logger(__name__)

MIN_TIMEOUT_S = 14.0


class GetQuoteArgs(BaseModel):
    symbol: str = Field(..., min_length=1, description="Ticker")
    currency: str = Field("USD", min_length=1, description="Currency code")
    exchange: str = Field(
        ...,
        min_length=1,
        description="Exchange code. SMART is allowed only for stocks to choose the best exchange. If the symbol is an index or may resolve to an index (IND), you MUST provide the real listing exchange and you MUST NOT use SMART. For indices, SMART is invalid and often fails. Examples: VIX -> CBOE, SPX -> CBOE, NDX -> NASDAQ.",
    )
    timeout_s: float = Field(
        30.0,
        gt=MIN_TIMEOUT_S,
        description="Timeout for quote fetch (clamped to 15s minimum)",
    )
    market_data_type: int = Field(
        1,
        description="IB market data type (1=real-time, 2=frozen, 3=delayed, 4=delayed-frozen). Default 3 (delayed) for reliability.",
    )
    regulatory_snapshot: bool = Field(False)


@register_tool(
    "get_quote",
    description="Retrieve market data quote for a given contract. Uses automatic fallback across market data types if the requested type times out.",
    args_model=GetQuoteArgs,
)
async def get_quote(args: Dict[str, Any]) -> Dict[str, Any]:
    a = GetQuoteArgs(**args)

    # Clamp timeout to a safe minimum
    effective_timeout = max(a.timeout_s, MIN_TIMEOUT_S)

    ibTools = IBTools.get_instance()
    ib = ibTools.ib

    async with ibTools.guarded():
        q, resolved_sec_type = await qualify_contract(
            ib,
            {
                "symbol": a.symbol,
                "exchange": a.exchange,
                "currency": a.currency,
            },
        )

        if resolved_sec_type == "IND":
            a.market_data_type = (
                3  # Force delayed for indices, as real-time is often unavailable
            )

        # --- Build the ordered list of market_data_types to try ---
        types_to_try = [a.market_data_type] + _FALLBACK_DATA_TYPES.get(
            a.market_data_type, []
        )

        last_error: Optional[str] = None
        used_data_type: Optional[int] = None

        for mdt in types_to_try:
            logger.debug(
                "get_quote %s: trying market_data_type=%d, timeout=%.1fs",
                a.symbol,
                mdt,
                effective_timeout,
            )
            ib.reqMarketDataType(mdt)

            try:
                t = await _request_snapshot(
                    ibTools.ib, q, effective_timeout, a.regulatory_snapshot
                )
            except Exception as e:
                last_error = str(e)
                logger.error(
                    "get_quote %s error with mdt=%d: %s", a.symbol, mdt, last_error
                )
                continue

            if t is not None:
                used_data_type = mdt
                break
        else:
            # All attempts exhausted
            logger.warning(
                "get_quote %s: all market_data_types exhausted, returning TIMEOUT",
                a.symbol,
            )
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
            "marketDataType": (
                _get_data_type_name(used_data_type) if used_data_type else None
            ),
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
