from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from db.db_tools import DBTools
from llm.tools.base import register_tool


class MemoryCreateArgs(BaseModel):
    title: str = Field(..., description="Title for the memory entry.")
    content: str = Field(..., min_length=1, description="The content of the memory entry.")
    memory_type: str = Field(..., description="Type/category for the memory entry.")
    source: Optional[str] = Field(None, description="Source or origin of the memory entry.")
    tags: Optional[List[str]] = Field(None, description="List of tags associated with the memory entry.")
    meta: Optional[Dict[str, Any]] = Field(None, description="Additional metadata for the memory entry.")

@register_tool("memory_create", description="Create a new memory entry in the system.", args_model=MemoryCreateArgs)
async def memory_create(args: Dict[str, Any]) -> Dict[str, Any]:
    a = MemoryCreateArgs(**args)

    dbTools = DBTools.get_instance()

    try:
        memory_created = dbTools.memory_create(
            a.content,
            a.memory_type,
            a.title,
            message_id=args.get("message_id"),
            source=a.source,
            tags=a.tags,
            meta=a.meta
        )
        
        return {
            "memory_id": str(memory_created.get("id")),
            "memory": memory_created
        }
    except Exception as e:
        return {
            "error": str(e)
        }