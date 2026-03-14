from typing import Any, Dict

from pydantic import BaseModel, Field

from db.db_tools import DBTools
from llm.tools.base import register_tool


class GetRunDetailsArgs(BaseModel):
    run_id: str = Field(..., description="ID of the run to retrieve details for.")


@register_tool(
    "get_run_details",
    description="Get details of a specific run, including messages and tool calls.",
    args_model=GetRunDetailsArgs,
    run=False,
)
async def get_run_details(args: Dict[str, Any]) -> Dict[str, Any]:
    a = GetRunDetailsArgs(**args)

    dbTools = DBTools.get_instance()
    run = dbTools.get_run_by_id(a.run_id)

    if not run:
        return {
            "status": "NOT_FOUND",
            "runId": a.run_id,
        }

    return {
        "id": run.id,
        "trigger_type": run.trigger_type,
        "provider": run.provider,
        "model": run.model,
        "started_at": run.started_at.isoformat(),
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "status": run.status,
        "messages": [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.created_at.isoformat(),
                "tool_calls": [
                    {
                        "id": tc.id,
                        "tool_name": tc.tool_name,
                        "input_payload": tc.input_payload,
                        "output_payload": tc.output_payload,
                        "status": tc.status,
                        "executed_at": tc.executed_at.isoformat(),
                    }
                    for tc in msg.tool_calls
                ],
            }
            for msg in run.messages
        ],
    }
