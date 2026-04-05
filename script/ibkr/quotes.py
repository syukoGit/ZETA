import asyncio
import logging
from typing import Dict, List, Optional

from ib_async import IB, Ticker

from ibkr.utils import clean_price

logger = logging.getLogger(__name__)

# Fallback chain: requested type → next best types
_FALLBACK_DATA_TYPES: Dict[int, List[int]] = {
    1: [3, 4],  # real-time → delayed → delayed-frozen
    2: [4, 3],  # frozen → delayed-frozen → delayed
    3: [4],  # delayed → delayed-frozen
    4: [3],  # delayed-frozen → delayed
}


def _get_data_type_name(mdt: int) -> str:
    return {
        1: "REAL-TIME",
        2: "FROZEN",
        3: "DELAYED",
        4: "DELAYED-FROZEN",
    }.get(mdt, f"UNKNOWN({mdt})")


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
            has_data = any(
                clean_price(getattr(t, f, None)) is not None
                for f in ("bid", "ask", "last", "close")
            )
            if has_data:
                return t
            logger.warning(
                "Ticker returned but no meaningful price fields for contract %s",
                contract.symbol,
            )
            return None
        return None
    except asyncio.TimeoutError:
        logger.warning(
            "reqTickersAsync timed out after %.1fs for %s", timeout_s, contract.symbol
        )
        return None


async def fetch_snapshot(
    ib: IB,
    contract,
    initial_data_type: int = 1,
    timeout_s: float = 15.0,
    regulatory_snapshot: bool = False,
) -> Optional[Ticker]:
    """
    Request a snapshot ticker for `contract`, starting with `initial_data_type` and
    falling back through _FALLBACK_DATA_TYPES on timeout or missing data.
    Returns the first successful Ticker, or None if all attempts fail.
    """
    for mdt in [initial_data_type] + _FALLBACK_DATA_TYPES.get(initial_data_type, []):
        logger.debug(
            "fetch_snapshot %s: trying market_data_type=%d (%s)",
            contract.symbol,
            mdt,
            _get_data_type_name(mdt),
        )
        ib.reqMarketDataType(mdt)
        t = await _request_snapshot(ib, contract, timeout_s, regulatory_snapshot)
        if t is not None:
            return t
    return None
