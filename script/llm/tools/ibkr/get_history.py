from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ibkr.ibTools import IBTools
from ibkr.contracts import qualify_contract
from llm.tools.base import register_tool


class GetHistoryArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    exchange: str = Field("SMART", min_length=1, description="Exchange code. Use 'SMART' for stocks. For indices, provide the listing exchange (e.g. CBOE for VIX).")
    currency: str = Field("USD", min_length=1)
    duration: str = Field("2 D", description='The amount of time to go back from the request\'s given end date and time', pattern="^([1-9][0-9]* (S|D|W|M|Y))+$")
    what_to_show: str = Field("TRADES", description='Type of data to show', pattern="^(TRADES|MIDPOINT|BID|ASK|BID_ASK|ADJUSTED_LAST|HISTORICAL_VOLATILITY|OPTION_IMPLIED_VOLATILITY)$")
    bar_size: str = Field("1 min", description='The data\'s granularity', pattern="^(1 sec|5 secs|10 secs|15 secs|30 secs|1 min|2 mins|3 mins|5 mins|10 mins|15 mins|20 mins|30 mins|1 hour|2 hours|3 hours|4 hours|8 hours|1 day|1 week|1 month)$")
    keepUpToDate: bool = Field(False, description='False (one-shot) or True (update of the last bar in progress); if True, endDateTime must be “” and the bar size must be ≥ 5 seconds.')
    use_rth: bool = False


@register_tool("get_history", description="Return historical market data bars for a given symbol.", args_model=GetHistoryArgs)
async def get_history(args: Dict[str, Any]) -> Dict[str, Any]:
    a = GetHistoryArgs(**args)

    ibTools = IBTools.get_instance()

    async with ibTools.ib_sem:
        q, resolved_sec_type = await qualify_contract(
            ibTools.ib,
            {
                "symbol": a.symbol,
                "exchange": a.exchange,
                "currency": a.currency,
            },
        )

        bars = await ibTools.ib.reqHistoricalDataAsync(
            q,
            endDateTime="",
            durationStr=a.duration,
            barSizeSetting=a.bar_size,
            whatToShow=a.what_to_show,
            useRTH=a.use_rth,
            formatDate=1,
            keepUpToDate=a.keepUpToDate,
        )
    
    out: list[Dict[str, Any]] = [{
        "time": b.date.isoformat(), "open": float(b.open), "high": float(b.high),
        "low": float(b.low), "close": float(b.close), "volume": float(b.volume)
    } for b in bars]

    return {
        "symbol": getattr(q, "symbol", a.symbol),
        "secType": resolved_sec_type,
        "exchange": getattr(q, "exchange", a.exchange),
        "currency": getattr(q, "currency", a.currency),
        "bars": out,
    }