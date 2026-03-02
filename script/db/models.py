from datetime import datetime
from typing import Optional, List
from uuid import uuid4

from sqlalchemy import (
    Text,
    Integer,
    ForeignKey,
    DateTime,
    JSON,
    Index,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import DeclarativeBase, relationship, Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from .time_utils import utc_now


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    trigger_type: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    messages: Mapped[List["Message"]] = relationship("Message", back_populates="run", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Run(id={self.id}, trigger_type='{self.trigger_type[:50] if self.trigger_type else None}...', status={self.status})>"


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("runs.id"), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_content: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    sequence_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, default=utc_now)

    # Relationships
    run: Mapped["Run"] = relationship("Run", back_populates="messages")
    tool_calls: Mapped[List["ToolCall"]] = relationship("ToolCall", back_populates="message", cascade="all, delete-orphan")
    memory_access_logs: Mapped[List["MemoryAccessLog"]] = relationship("MemoryAccessLog", back_populates="message", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_messages_run_id_sequence", "run_id", "sequence_index"),
    )

    def __repr__(self) -> str:
        return f"<Message(id={self.id}, role={self.role}, sequence_index={self.sequence_index})>"


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False)
    tool_name: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    input_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    output_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    executed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, default=utc_now)

    # Relationships
    message: Mapped["Message"] = relationship("Message", back_populates="tool_calls")

    __table_args__ = (
        Index("ix_tool_calls_message_id", "message_id"),
        Index("ix_tool_calls_tool_name", "tool_name"),
    )

    def __repr__(self) -> str:
        return f"<ToolCall(id={self.id}, tool_name={self.tool_name}, status={self.status})>"


class MemoryEntry(Base):
    __tablename__ = "memory_entries"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    memory_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    source: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tags: Mapped[Optional[List[str]]] = mapped_column(ARRAY(Text), nullable=True)
    meta: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, onupdate=utc_now)
    embedding = mapped_column(Vector(1024), nullable=True)

    # Relationships
    access_logs: Mapped[List["MemoryAccessLog"]] = relationship("MemoryAccessLog", back_populates="memory", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_memory_entries_memory_type", "memory_type"),
        Index("ix_memory_entries_status", "status"),
        Index("ix_memory_entries_tags", "tags", postgresql_using="gin"),
    )

    def __repr__(self) -> str:
        return f"<MemoryEntry(id={self.id}, title='{self.title}', type={self.memory_type}, status={self.status})>"


class MemoryAccessLog(Base):
    __tablename__ = "memory_access_log"

    id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    message_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("messages.id"), nullable=False)
    memory_id: Mapped[UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("memory_entries.id"), nullable=False)
    access_type: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # 'read' or 'write'
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, default=utc_now)

    # Relationships
    message: Mapped["Message"] = relationship("Message", back_populates="memory_access_logs")
    memory: Mapped["MemoryEntry"] = relationship("MemoryEntry", back_populates="access_logs")

    __table_args__ = (
        Index("ix_memory_access_log_message_id", "message_id"),
        Index("ix_memory_access_log_memory_id", "memory_id"),
    )

    def __repr__(self) -> str:
        return f"<MemoryAccessLog(id={self.id}, access_type={self.access_type}, reason='{self.reason[:30] if self.reason else None}...')>"
