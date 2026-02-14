from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from db.db_tools import DBTools
from llm.tools.base import register_tool


class MemoryUpdateArgs(BaseModel):
    memory_id: str = Field(..., description="The unique identifier of the memory entry to update.")
    reason: str = Field(..., description="The reason for updating the memory entry.")
    content: Optional[str] = Field(None, description="The new content of the memory entry. None to keep unchanged.")
    meta: Optional[Dict[str, Any]] = Field(None, description="Additional metadata for the memory entry. None to keep unchanged.")
    tags: Optional[List[str]] = Field(None, description="List of tags associated with the memory entry. None to keep unchanged.")


@register_tool("memory_update", description="Update an existing memory entry in the system.", args_model=MemoryUpdateArgs)
async def memory_update(args: Dict[str, Any]) -> Dict[str, Any]:
    a = MemoryUpdateArgs(**args)

    dbTools = DBTools.get_instance()

    try:
        memory_updated = dbTools.memory_update(
            a.memory_id,
            args.get("message_id"),
            a.reason,
            content=a.content,
            meta=a.meta,
            status=None,
            tags=a.tags,
            message_id=args.get("message_id")
        )
        
        return {
            "memory_id": str(a.memory_id),
            "memory": memory_updated
        }
    except Exception as e:
        return {
            "memory_id": str(a.memory_id),
            "error": str(e)
        }