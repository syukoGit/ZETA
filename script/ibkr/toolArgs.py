from typing import Literal, Optional
from pydantic import BaseModel, Field, model_validator

class NoArgs(BaseModel):
    pass

# Order-related argument models
class PlaceOrderArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    exchange: str = Field("SMART", min_length=1)
    currency: str = Field("USD", min_length=1)
    primary_exchange: Optional[str] = Field(None, min_length=1)

    side: Literal["BUY", "SELL"] = Field(..., description="Order side for the entry order")
    qty: float = Field(..., gt=0)

    order_type: Literal["MKT", "LMT"] = Field(..., description="Type of the order")
    limit_price: Optional[float] = None

    @model_validator(mode="after")
    def validate_logic(self):
        if self.order_type == "LMT" and self.limit_price is None:
            raise ValueError("limit_price required for LMT orders")
        return self

class CancelOrderArgs(BaseModel):
    order_id: int = Field(..., gt=0)

class ModifyOrderArgs(BaseModel):
    order_id: int = Field(..., gt=0)
    new_limit_price: Optional[float] = Field(None, gt=0)
    new_qty: Optional[int] = Field(None, gt=0)
    time_in_force: Optional[str] = None

class PlaceBracketOrderArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    exchange: str = Field("SMART")
    currency: str = Field("USD")
    primary_exchange: Optional[str] = None

    # Parent
    side: Literal["BUY", "SELL"] = Field(..., description="Order side for the entry order")
    qty: int = Field(..., gt=0)
    entry_type: Literal["MKT", "LMT"] = Field(..., description="Type of the entry order")
    entry_limit_price: Optional[float] = Field(None, gt=0)

    # Take profit
    take_profit_price: float = Field(..., gt=0)

    # Stop loss
    stop_loss_price: float = Field(..., gt=0)

    # Time in force
    tif: Literal["DAY", "GTC"] = Field("DAY", description="Time in force for the orders")

    @model_validator(mode="after")
    def validate_prices(self):
        if self.side == "BUY":
            if not (self.stop_loss_price < self.take_profit_price):
                raise ValueError("BUY: stop_loss must be < take_profit")
        else:
            if not (self.stop_loss_price > self.take_profit_price):
                raise ValueError("SELL: stop_loss must be > take_profit")

        return self

class PlaceOcoOrderArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    exchange: str = Field("SMART", min_length=1)
    currency: str = Field("USD", min_length=1)
    primary_exchange: Optional[str] = Field(None, min_length=1)

    # Position
    side: Literal["BUY", "SELL"] = Field(..., description="Order side for the entry order")
    qty: int = Field(..., gt=0)

    # Take Profit
    take_profit_price: float = Field(..., gt=0)

    # Stop Loss
    stop_loss_price: float = Field(..., gt=0)

    tif: Literal["DAY", "GTC"] = Field("DAY", description="Time in force for the orders")

    @model_validator(mode="after")
    def validate_logic(self):
        # SELL
        if self.side == "SELL":
            if not self.stop_loss_price < self.take_profit_price:
                raise ValueError("SELL OCO: stop_loss < take_profit required")
        # BUY
        else:
            if not self.stop_loss_price > self.take_profit_price:
                raise ValueError("BUY OCO: stop_loss > take_profit required")
        return self

# Market data-related argument models
class GetQuoteArgs(BaseModel):
    symbol: str = Field(..., min_length=1, description="Ticker")
    currency: str = Field("USD", min_length=1, description="Currency code")
    exchange: str = Field("SMART", min_length=1, description="SMART recommended")
    primary_exchange: Optional[str] = Field("NASDAQ", description="Optional primary exchange")
    timeout_s: float = Field(6.0, gt=0, description="Timeout for quote fetch")
    regulatory_snapshot: bool = Field(False)

class GetHistoryArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    duration: str = Field("2 D", description='The amount of time to go back from the request\'s given end date and time', pattern="^([1-9][0-9]* (S|D|W|M|Y))+$")
    what_to_show: str = Field("TRADES", description='Type of data to show', pattern="^(TRADES|MIDPOINT|BID|ASK|BID_ASK|ADJUSTED_LAST|HISTORICAL_VOLATILITY|OPTION_IMPLIED_VOLATILITY)$")
    bar_size: str = Field("1 min", description='The data\'s granularity', pattern="^(1 sec|5 secs|10 secs|15 secs|30 secs|1 min|2 mins|3 mins|5 mins|10 mins|15 mins|20 mins|30 mins|1 hour|2 hours|3 hours|4 hours|8 hours|1 day|1 week|1 month)$")
    keepUpToDate: bool = Field(False, description='False (one-shot) or True (update of the last bar in progress); if True, endDateTime must be “” and the bar size must be ≥ 5 seconds.')
    use_rth: bool = False

class GetVolatilityMetricsArgs(BaseModel):
    symbol: str = Field(..., min_length=1)
    exchange: str = Field("SMART", min_length=1)
    currency: str = Field("USD", min_length=1)
    primary_exchange: Optional[str] = Field(None, min_length=1)

    lookback_days: int = Field(20, ge=5, le=252)
    use_rth: bool = Field(True)

    bar_size: Literal["1 sec", "5 secs", "10 secs", "15 secs", "30 secs", "1 min", "2 mins", "3 mins", "5 mins", "10 mins", "15 mins", "20 mins", "30 mins", "1 hour", "2 hours", "3 hours", "4 hours", "8 hours", "1 day", "1 week", "1 month"] = Field("1 day", description='The data\'s granularity')
    duration: str = Field("30 D", description='The amount of time to go back from the request\'s given end date and time', pattern="^([1-9][0-9]* (S|D|W|M|Y))+$") 