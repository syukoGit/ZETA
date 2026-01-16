from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid6 import uuid7

from sqlalchemy import (
    String, Text, DateTime, ForeignKey, CheckConstraint, Index, JSON
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

def utcnow() -> datetime:
    return datetime.now(timezone.utc)

class Base(DeclarativeBase):
    pass

class Conversation(Base):
    __tablename__ = "conversations"

    conversation_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid7()))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)      # ex: 'xai'
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)         # ex: 'grok-...'
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    items: Mapped[list["Item"]] = relationship(back_populates="conversation", cascade="all, delete-orphan")

class Item(Base):
    __tablename__ = "items"

    item_id: Mapped[str] = mapped_column(String, primary_key=True, default=lambda: str(uuid7()))
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.conversation_id", ondelete="CASCADE"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    kind: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String)
    content: Mapped[Optional[str]] = mapped_column(Text)
    payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON)

    parent_item_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("items.item_id"))

    status: Mapped[Optional[str]] = mapped_column(String)
    error: Mapped[Optional[str]] = mapped_column(Text)

    conversation: Mapped["Conversation"] = relationship(back_populates="items")
    parent: Mapped[Optional["Item"]] = relationship(remote_side="Item.item_id")

    __table_args__ = (
        CheckConstraint("parent_item_id IS NULL OR parent_item_id <> item_id", name="ck_item_no_self_parent"),
        Index("idx_item_conv_time", "conversation_id", "created_at", "item_id"),
        Index("idx_item_kind_time", "kind", "created_at"),
        Index("idx_item_parent", "parent_item_id"),
    )