from datetime import datetime, timezone
import math
from typing import Any, Dict, Literal, Optional

import numpy as np
from pydantic import BaseModel, Field

from ibkr.ibTools import IBTools
from ibkr.contracts import qualify_contract
from llm.tools.base import register_tool


class GetVolatilityMetricsArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    sec_type: Optional[str] = Field(None, description="IB contract type: STK (stock/ETF) or IND (index). If omitted, auto-detection is attempted.")
    exchange: str = Field("SMART", min_length=1, description="Exchange code. Use 'SMART' for stocks. For indices, provide the listing exchange (e.g. CBOE for VIX).")
    currency: str = Field("USD", min_length=1)

    lookback_days: int = Field(20, ge=5, le=252)
    use_rth: bool = Field(True)

    bar_size: Literal["1 sec", "5 secs", "10 secs", "15 secs", "30 secs", "1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins", "20 mins", "30 mins", "1 hour", "2 hours", "3 hours", "4 hours", "8 hours", "1 day", "1 week", "1 month"] = Field("1 day", description='The data\'s granularity')
    duration: str = Field("30 D", description='The amount of time to go back from the request\'s given end date and time', pattern="^([1-9][0-9]* (S|D|W|M|Y))+$")


@register_tool("get_volatility_metrics", description="Retrieve volatility metrics for a given contract.", args_model=GetVolatilityMetricsArgs)
async def get_volatility_metrics(args: Dict[str, Any]) -> Dict[str, Any]:
    a = GetVolatilityMetricsArgs(**args)

    ibTools = IBTools.get_instance()

    async with ibTools.ib_sem:
        q, resolved_sec_type = await qualify_contract(
            ibTools.ib,
            {
                "symbol": a.symbol,
                "sec_type": a.sec_type,
                "exchange": a.exchange,
                "currency": a.currency,
            },
        )

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
            "symbol": getattr(q, "symbol", a.symbol),
            "secType": resolved_sec_type,
            "lookback_days": a.lookback_days,
            "atr": atr,
            "realized_vol": realized_vol,
            "avg_range": avg_range,
            "avg_gap_pct": avg_gap,
            "useRTH": a.use_rth,
            "asOf": datetime.now(timezone.utc).isoformat(),
        }
