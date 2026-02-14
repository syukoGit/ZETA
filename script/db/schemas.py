from datetime import datetime
from typing import Optional, List, Dict, Any
from uuid import UUID

from pydantic import BaseModel, Field


# ========== Run Schemas ==========

class RunCreate(BaseModel):
    """Schema for creating a new run."""
    objective: str
    trigger_type: Optional[str] = "user"
    model_name: Optional[str] = None
    system_prompt_hash: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class RunUpdate(BaseModel):
    """Schema for updating a run."""
    status: Optional[str] = None
    final_output: Optional[Dict[str, Any]] = None


class RunResponse(BaseModel):
    """Schema for run response."""
    id: UUID
    objective: Optional[str]
    trigger_type: Optional[str]
    model_name: Optional[str]
    status: Optional[str]
    started_at: Optional[datetime]
    ended_at: Optional[datetime]
    final_output: Optional[Dict[str, Any]]
    metadata: Optional[Dict[str, Any]]

    class Config:
        from_attributes = True


# ========== Message Schemas ==========

class MessageCreate(BaseModel):
    """Schema for creating a new message."""
    run_id: UUID
    role: str
    content: str
    sequence_index: Optional[int] = None


class MessageResponse(BaseModel):
    """Schema for message response."""
    id: UUID
    run_id: UUID
    role: Optional[str]
    content: Optional[str]
    sequence_index: Optional[int]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ========== Memory Schemas ==========

class MemoryCreate(BaseModel):
    """Schema for creating a new memory entry."""
    content: str
    memory_type: str
    title: Optional[str] = None
    source: Optional[str] = None
    tags: Optional[List[str]] = Field(default_factory=list)
    metadata: Optional[Dict[str, Any]] = None


class MemorySuggestionSchema(BaseModel):
    """Schema for suggesting a new memory."""
    content: str
    memory_type: str
    title: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    reason: str = ""


class MemorySearchQuery(BaseModel):
    """Schema for memory search query."""
    query: str
    limit: int = Field(default=5, ge=1, le=50)
    memory_types: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    min_similarity: float = Field(default=0.5, ge=0.0, le=1.0)


class MemoryResponse(BaseModel):
    """Schema for memory response."""
    id: UUID
    memory_type: Optional[str]
    title: Optional[str]
    content: Optional[str]
    status: Optional[str]
    source: Optional[str]
    tags: Optional[List[str]]
    metadata: Optional[Dict[str, Any]]
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class MemorySearchResult(BaseModel):
    """Schema for memory search result."""
    id: UUID
    title: Optional[str]
    content: str
    memory_type: str
    similarity: float
    tags: List[str]
    created_at: Optional[datetime]


class ContradictionSignal(BaseModel):
    """Schema for signaling a contradiction."""
    memory_id: UUID
    contradicting_content: str
    reason: str


class ObsoleteSignal(BaseModel):
    """Schema for marking memory as obsolete."""
    memory_id: UUID
    reason: str


# ========== Tool Call Schemas ==========

class ToolCallCreate(BaseModel):
    """Schema for creating a tool call record."""
    message_id: UUID
    tool_name: str
    input_payload: Optional[Dict[str, Any]] = None


class ToolCallComplete(BaseModel):
    """Schema for completing a tool call."""
    output_payload: Optional[Dict[str, Any]] = None
    success: bool = True


class ToolCallResponse(BaseModel):
    """Schema for tool call response."""
    id: UUID
    message_id: UUID
    tool_name: Optional[str]
    input_payload: Optional[Dict[str, Any]]
    output_payload: Optional[Dict[str, Any]]
    status: Optional[str]
    executed_at: Optional[datetime]

    class Config:
        from_attributes = True


# ========== Memory Access Log Schemas ==========

class MemoryAccessLogResponse(BaseModel):
    """Schema for memory access log response."""
    id: UUID
    message_id: UUID
    memory_id: UUID
    access_type: Optional[str]
    reason: Optional[str]
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ========== Aggregate Schemas ==========

class RunWithMessages(RunResponse):
    """Run with its messages."""
    messages: List[MessageResponse] = Field(default_factory=list)


class MessageWithToolCalls(MessageResponse):
    """Message with its tool calls."""
    tool_calls: List[ToolCallResponse] = Field(default_factory=list)


class MemoryWithAccessLogs(MemoryResponse):
    """Memory with its access logs."""
    access_logs: List[MemoryAccessLogResponse] = Field(default_factory=list)
