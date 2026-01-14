from typing import Optional
from pydantic import BaseModel, Field


class GetPositionsArgs(BaseModel):
    pass

class GetCashBalanceArgs(BaseModel):
    pass

class GetPnlArgs(BaseModel):
    pass

class GetOrdersArgs(BaseModel):
    pass

class GetHistoryArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    duration: str = Field("2 D", description='The amount of time to go back from the request\'s given end date and time', pattern="^([1-9][0-9]* (S|D|W|M|Y))+$")
    what_to_show: str = Field("TRADES", description='Type of data to show', pattern="^(TRADES|MIDPOINT|BID|ASK|BID_ASK|ADJUSTED_LAST|HISTORICAL_VOLATILITY|OPTION_IMPLIED_VOLATILITY)$")
    bar_size: str = Field("1 min", description='The data\'s granularity', pattern="^(1 sec|5 secs|10 secs|15 secs|30 secs|1 min|2 mins|3 mins|5 mins|10 mins|15 mins|20 mins|30 mins|1 hour|2 hours|3 hours|4 hours|8 hours|1 day|1 week|1 month)$")
    keepUpToDate: bool = Field(False, description='False (one-shot) or True (update of the last bar in progress); if True, endDateTime must be “” and the bar size must be ≥ 5 seconds.')
    use_rth: bool = False

class PlaceOrderArgs(BaseModel):
    symbol: str
    side: str = Field(..., pattern="^(BUY|SELL)$")
    qty: float = Field(..., gt=0)
    order_type: str = Field(..., pattern="^(MKT|LMT)$")
    limit_price: Optional[float] = None

    @staticmethod
    def validate_limit(values):
        return values