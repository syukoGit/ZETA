from typing import Any, Dict, Optional

from ib_async import Stock
from pydantic import BaseModel, Field

from ibkr.ibTools import IBTools
from llm.tools.base import register_tool


class GetHistoryArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    exchange: str = Field("SMART", min_length=1, description="Exchange code. Use 'SMART' for IBKR to choose the best exchange")
    primary_exchange: Optional[str] = Field(None, min_length=1)
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

    contract: Stock
    if (a.primary_exchange):
        contract = Stock(a.symbol, a.exchange, a.currency, primaryExchange=a.primary_exchange)
    else:
        contract = Stock(a.symbol, a.exchange, a.currency)

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

    return {"symbol": contract.symbol, "exchange": contract.exchange, "bars": out}