from datetime import datetime
from typing import Any, Dict

from db.db_tools import DBTools
from llm.tools.base import register_tool


@register_tool("get_runs_to_review", description="Retrieve runs that have been executed since the last performance review.", args_model=None, run=False)
async def get_runs_to_review(_: Dict[str, Any]) -> Dict[str, Any]:
    dbTools = DBTools.get_instance()
    
    last_review = dbTools.get_filtered_runs(trigger_type="performance_review", status="completed", limit=1)
    last_review_time = last_review[0].started_at if last_review else datetime.min

    runs_to_review = dbTools.get_filtered_runs(
        trigger_type="llm_call",
        after=last_review_time,
    )

    return {
        "runs": [
            {
                "id": run.id,
                "trigger_type": run.trigger_type,
                "started_at": run.started_at.isoformat(),
                "ended_at": run.ended_at.isoformat() if run.ended_at else None,
                "status": run.status,
            }
            for run in runs_to_review
        ]
    }