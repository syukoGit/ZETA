from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from db.db_tools import DBTools
from llm.tools.base import register_tool


class MemoryDeprecateArgs(BaseModel):
    memory_id: str = Field(..., description="The unique identifier of the memory entry to deprecate.")
    reason: str = Field(..., description="The reason for deprecating the memory entry.")


@register_tool("memory_deprecate", description="Deprecate an existing memory entry in the system.", args_model=MemoryDeprecateArgs)
async def memory_deprecate(args: Dict[str, Any]) -> Dict[str, Any]:
    a = MemoryDeprecateArgs(**args)

    dbTools = DBTools.get_instance()

    try:
        memory_id = dbTools.memory_deprecate(
            a.memory_id,
            a.reason,
            message_id=args.get("message_id")
        )
        
        return {
            "memory_id": str(memory_id),
            "message": "Memory entry deprecated successfully."
        }
    except Exception as e:
        return {
            "memory_id": str(memory_id),
            "error": str(e)
        }