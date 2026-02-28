from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from llm.tools.base import register_tool


from typing import List, Optional
from pydantic import BaseModel, Field


class ClosePerformanceReviewArgs(BaseModel):
    portfolio_overview: str = Field(
        ...,
        description="Objective overview of portfolio evolution and run behavior since last review."
    )

    strategic_diagnosis: str = Field(
        ...,
        description="Clear assessment of current edge quality, regime alignment, and structural strengths/weaknesses."
    )

    next_wave_directive: str = Field(
        ...,
        description="Primary strategic direction for upcoming runs."
    )

    risk_framework_update: str = Field(
        ...,
        description="Explicit risk management adjustments for next runs."
    )

    key_adjustments: Optional[List[str]] = Field(
        default=None,
        description="Concise list of concrete adjustments to apply immediately."
    )

    memory_actions: Optional[List[str]] = Field(
        default=None,
        description="Required updates to strategic memory (reinforce, deprecate, merge, delete)."
    )

    confidence_level: int = Field(
        ...,
        ge=0,
        le=10,
        description="Confidence in current strategic posture (0=unstable, 10=validated edge)."
    )

@register_tool("close_performance_review", description="Close the performance review with structured insights and adjustments.", args_model=ClosePerformanceReviewArgs, run=False)
async def close_performance_review(args: Dict[str, Any]) -> Dict[str, str]:
    a = ClosePerformanceReviewArgs(**args)

    return {
        "portfolio_overview": a.portfolio_overview,
        "strategic_diagnosis": a.strategic_diagnosis,
        "next_wave_directive": a.next_wave_directive,
        "risk_framework_update": a.risk_framework_update,
        "key_adjustments": a.key_adjustments,
        "memory_actions": a.memory_actions,
        "confidence_level": a.confidence_level
    }