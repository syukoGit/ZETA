from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from db.db_tools import DBTools
from llm.tools.base import register_tool


class SearchMemoryArgs(BaseModel):
    query: str = Field(..., min_length=1, description="The search query to find relevant memory entries.")
    limit: int = Field(..., gt=0, description="The maximum number of relevant memory entries to return.")
    memory_types: Optional[List[str]] = Field(None, description="Optional list of memory types to include.")
    status: Optional[List[str]] = Field(None, description="Optional list of statuses to include.")
    tags: Optional[List[str]] = Field(None, description="Optional list of tags; entry must overlap at least one.")
    meta_filters: Optional[Dict[str, Any]] = Field(None, description="Optional JSON filters that must match exactly.")
    min_similarity: float = Field(0.5, ge=0.0, le=1.0, description="Minimum cosine similarity threshold.")


@register_tool("search_memory", description="Search the memory system for relevant entries based on a query.", args_model=SearchMemoryArgs) 
async def search_memory(args: Dict[str, Any]) -> Dict[str, Any]:
    a = SearchMemoryArgs(**args)

    dbTools = DBTools.get_instance()

    try:
        results = dbTools.search_memory(
            a.query,
            args.get("message_id"),
            a.limit,
            a.memory_types,
            a.status,
            a.tags,
            a.meta_filters,
            a.min_similarity,
        )
    except Exception as e:
        return {"search_query": a.query, "error": str(e)}

    return {"search_query": a.query, "results": results}