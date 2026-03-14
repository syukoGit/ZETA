from typing import Any, Dict, List

from pydantic import BaseModel, Field

from llm.tools.base import register_tool


class ExecutedAction(BaseModel):
    symbol: str = Field(
        ..., description="Ticker symbol of the asset traded during this run."
    )
    side: str = Field(
        ..., pattern="^(BUY|SELL)$", description="Trade side executed during this run"
    )
    quantity: float = Field(..., gt=0, description="Quantity of the asset traded.")
    price: float = Field(..., gt=0, description="Execution price of the trade.")


class SummaryArgs(BaseModel):
    trades_executed: List[ExecutedAction] = Field(
        ...,
        description="List of trades executed during this run. Empty list if no trades were executed.",
    )
    run_commentary: str = Field(
        ...,
        min_length=10,
        max_length=300,
        description=(
            "Short factual description of what happened during this run. "
            "Must describe measurable events only. "
            "No predictions, no strategic justification, no market interpretation."
        ),
    )


class CloseRunArgs(BaseModel):
    summary: SummaryArgs = Field(
        ..., description="Structured factual summary of this run."
    )
    time_before_next_run_s: float = Field(
        ...,
        ge=1,
        le=300,
        description="Waiting time in seconds before the next run can be started.",
    )


@register_tool(
    "close_run",
    description="Close the current run with a summary and specify time before the next run can start.",
    args_model=CloseRunArgs,
    review=False,
)
async def close_run(args: Dict[str, Any]) -> Dict[str, Any]:
    a = CloseRunArgs(**args)

    return {
        "summary": a.summary.model_dump(),
        "time_before_next_run_s": a.time_before_next_run_s,
    }
