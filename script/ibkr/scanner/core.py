import asyncio
import logging

from ib_async import ScannerSubscription, Stock, TagValue

from config import ScanEntryConfig, ScannerConfig, config
from ibkr.ibTools import IBTools
from ibkr.quotes import fetch_snapshot
from ibkr.utils import clean_price, clean_size
from phase_resolver import get_current_phase

logger = logging.getLogger(__name__)


async def _run_single_scan(scan: ScanEntryConfig, cfg: ScannerConfig) -> list[dict]:
    """Execute one IBKR scanner subscription and return raw symbol rows."""
    ibTools = IBTools.get_instance()

    tag_values = [
        TagValue("priceAbove", str(cfg.min_price)),
        TagValue("priceBelow", str(cfg.max_price)),
        TagValue("avgVolumeAbove", str(cfg.min_volume)),
        # IBKR marketCapAbove is in USD millions
        TagValue("marketCapAbove1e6", str(int(cfg.min_market_cap / 1_000_000))),
    ]

    subscription = ScannerSubscription(
        instrument="STK",
        locationCode=cfg.location_code,
        scanCode=scan.code,
        numberOfRows=cfg.top_n * 2,  # over-fetch; merge will truncate to top_n
    )

    async with ibTools.guarded():
        scan_data = await ibTools.ib.reqScannerDataAsync(subscription, [], tag_values)

    rows = []
    for item in scan_data:
        cd = getattr(item, "contractDetails", None)
        contract = getattr(cd, "contract", None)
        symbol = getattr(contract, "symbol", None)
        if not symbol:
            continue
        rows.append(
            {
                "symbol": symbol,
                "rank": getattr(item, "rank", None),
                "distance": getattr(item, "distance", None),
            }
        )
    return rows


async def _enrich_with_quotes(symbols: list[str]) -> dict[str, dict]:
    """Batch-fetch snapshot quotes (real-time with fallback) for a list of symbols."""
    ibTools = IBTools.get_instance()
    ib = ibTools.ib

    async with ibTools.guarded():
        contracts = [Stock(sym, "SMART", "USD") for sym in symbols]
        await ib.qualifyContractsAsync(*contracts)

        async def _fetch(contract) -> tuple[str, dict]:
            t = await fetch_snapshot(ib, contract)
            if not t:
                raise ValueError(f"No market data for {contract.symbol}")

            price = clean_price(t.last) or clean_price(t.close)
            volume = clean_size(t.volume)
            return contract.symbol, {
                "price": price,
                "volume": volume,
            }

        pairs = await asyncio.gather(
            *[_fetch(c) for c in contracts], return_exceptions=True
        )

    result = {}
    for item in pairs:
        if isinstance(item, Exception):
            continue
        sym, data = item
        result[sym] = data
    return result


async def run_market_scan() -> dict:
    """
    Run all phase-relevant IBKR scans in parallel, merge, score, and return top N.
    Safe to call when scanner.enabled is False (returns empty results immediately).
    """
    cfg = config().scanner
    phase = get_current_phase().phase.value

    if not cfg.enabled:
        return {"phase": phase, "scans_executed": [], "results": []}

    active_scans = [s for s in cfg.scans if not s.phases or phase in s.phases]

    if not active_scans:
        return {"phase": phase, "scans_executed": [], "results": []}

    raw_results = await asyncio.gather(
        *[_run_single_scan(s, cfg) for s in active_scans],
        return_exceptions=True,
    )

    # Merge: symbol → {score, appeared_in, distance}
    merged: dict[str, dict] = {}
    executed: list[str] = []

    for scan_spec, result in zip(active_scans, raw_results):
        if isinstance(result, Exception):
            logger.warning("Scan %s failed (ignored): %s", scan_spec.code, result)
            continue
        executed.append(scan_spec.code)
        for row in result:
            sym = row["symbol"]
            if sym not in merged:
                merged[sym] = {
                    "score": 0,
                    "appeared_in": [],
                    "distance": row.get("distance"),
                }
            merged[sym]["score"] += scan_spec.score
            merged[sym]["appeared_in"].append(scan_spec.code)

    # Sort: score desc, then appearances count desc as tie-break
    sorted_items = sorted(
        merged.items(),
        key=lambda kv: (-kv[1]["score"], -len(kv[1]["appeared_in"])),
    )[: cfg.top_n]

    quotes = await _enrich_with_quotes([sym for sym, _ in sorted_items])

    results = [
        {
            "symbol": sym,
            "score": data["score"],
            "appeared_in": data["appeared_in"],
            **quotes.get(sym, {"price": None, "volume": None}),
        }
        for sym, data in sorted_items
    ]

    return {
        "phase": phase,
        "scans_executed": executed,
        "results": results,
    }
