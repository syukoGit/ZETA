from typing import Any, Dict
from uuid import UUID

from pydantic import BaseModel, Field

from db.db_tools import DBTools
from llm.tools.base import register_tool


class MemoryGetByIdArgs(BaseModel):
    memory_id: UUID = Field(..., description="The unique identifier of the memory entry to retrieve.")

@register_tool("memory_get_by_id", description="Retrieve a memory entry by its unique ID.", args_model=MemoryGetByIdArgs)
async def memory_get_by_id(args: Dict[str, Any]) -> Dict[str, Any]:
    a = MemoryGetByIdArgs(**args)

    dbTools = DBTools.get_instance()

    try:
        memory_entry = dbTools.memory_get_by_id(a.memory_id, args.get("message_id"))

        if memory_entry is None:
            return {"memory_id": str(a.memory_id), "error": "Memory entry not found."}
        
        return {"memory_id": str(a.memory_id), "entry": memory_entry}
    except Exception as e:
        return {"memory_id": str(a.memory_id), "error": str(e)}