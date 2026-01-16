from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from contextlib import contextmanager

from sqlalchemy.orm import Session
from sqlalchemy import select, desc

from db.engine import SessionLocal, engine
from db.models import Base, Conversation, Item


def init_db() -> None:
    """Crée toutes les tables définies dans les modèles."""
    Base.metadata.create_all(bind=engine)


@contextmanager
def get_session():
    """Context manager pour obtenir une session de base de données."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


class ConversationRepository:
    """Repository pour gérer les conversations et leurs items."""

    def __init__(self, session: Session):
        self.session = session

    # ─────────────────────────────────────────────────────────────────────────
    # Conversation methods
    # ─────────────────────────────────────────────────────────────────────────

    def create_conversation(
        self,
        provider: str = "xai",
        model: str = "grok-4-1-fast-reasoning",
        metadata: Optional[dict[str, Any]] = None,
    ) -> Conversation:
        """Crée une nouvelle conversation."""
        conversation = Conversation(
            provider=provider,
            model=model,
            metadata_json=metadata,
        )
        self.session.add(conversation)
        self.session.flush()  # Pour obtenir l'ID généré
        return conversation

    def get_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Récupère une conversation par son ID."""
        return self.session.get(Conversation, conversation_id)

    def get_all_conversations(self, limit: int = 100) -> list[Conversation]:
        """Récupère toutes les conversations, ordonnées par date de début décroissante."""
        stmt = (
            select(Conversation)
            .order_by(desc(Conversation.started_at))
            .limit(limit)
        )
        return list(self.session.scalars(stmt).all())

    def end_conversation(self, conversation_id: str) -> Optional[Conversation]:
        """Marque une conversation comme terminée."""
        conversation = self.get_conversation(conversation_id)
        if conversation:
            conversation.ended_at = datetime.now(timezone.utc)
            self.session.flush()
        return conversation

    def delete_conversation(self, conversation_id: str) -> bool:
        """Supprime une conversation et tous ses items (cascade)."""
        conversation = self.get_conversation(conversation_id)
        if conversation:
            self.session.delete(conversation)
            self.session.flush()
            return True
        return False

    # ─────────────────────────────────────────────────────────────────────────
    # Item methods
    # ─────────────────────────────────────────────────────────────────────────

    def add_item(
        self,
        conversation_id: str,
        kind: str,
        role: Optional[str] = None,
        content: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
        parent_item_id: Optional[str] = None,
        status: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Item:
        """
        Ajoute un item à une conversation.
        
        Args:
            conversation_id: ID de la conversation
            kind: Type de l'item ('message', 'tool_call', 'tool_result', 'system', etc.)
            role: Rôle de l'item ('user', 'assistant', 'system', 'tool')
            content: Contenu textuel de l'item
            payload: Données JSON additionnelles (arguments de tool, metadata, etc.)
            parent_item_id: ID de l'item parent (pour les réponses de tools)
            status: Statut de l'item ('pending', 'completed', 'failed')
            error: Message d'erreur si applicable
        """
        item = Item(
            conversation_id=conversation_id,
            kind=kind,
            role=role,
            content=content,
            payload_json=payload,
            parent_item_id=parent_item_id,
            status=status,
            error=error,
        )
        self.session.add(item)
        self.session.flush()
        return item

    def add_system_message(self, conversation_id: str, content: str) -> Item:
        """Ajoute un message système à la conversation."""
        return self.add_item(
            conversation_id=conversation_id,
            kind="message",
            role="system",
            content=content,
        )

    def add_user_message(self, conversation_id: str, content: str) -> Item:
        """Ajoute un message utilisateur à la conversation."""
        return self.add_item(
            conversation_id=conversation_id,
            kind="message",
            role="user",
            content=content,
        )

    def add_assistant_message(
        self,
        conversation_id: str,
        content: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> Item:
        """Ajoute une réponse de l'assistant à la conversation."""
        return self.add_item(
            conversation_id=conversation_id,
            kind="message",
            role="assistant",
            content=content,
            payload=payload,
        )

    def add_tool_call(
        self,
        conversation_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        tool_call_id: Optional[str] = None,
    ) -> Item:
        """Ajoute un appel de tool à la conversation."""
        return self.add_item(
            conversation_id=conversation_id,
            kind="tool_call",
            role="assistant",
            content=tool_name,
            payload={
                "tool_call_id": tool_call_id,
                "name": tool_name,
                "arguments": arguments,
            },
            status="pending",
        )

    def add_tool_result(
        self,
        conversation_id: str,
        tool_name: str,
        result: Any,
        parent_item_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Item:
        """Ajoute le résultat d'un appel de tool à la conversation."""
        return self.add_item(
            conversation_id=conversation_id,
            kind="tool_result",
            role="tool",
            content=str(result) if result else None,
            payload={"name": tool_name, "result": result},
            parent_item_id=parent_item_id,
            status="failed" if error else "completed",
            error=error,
        )

    def get_conversation_items(
        self,
        conversation_id: str,
        kind: Optional[str] = None,
    ) -> list[Item]:
        """
        Récupère tous les items d'une conversation.
        
        Args:
            conversation_id: ID de la conversation
            kind: Filtrer par type d'item (optionnel)
        """
        stmt = (
            select(Item)
            .where(Item.conversation_id == conversation_id)
            .order_by(Item.created_at, Item.item_id)
        )
        if kind:
            stmt = stmt.where(Item.kind == kind)
        return list(self.session.scalars(stmt).all())

    def get_conversation_messages(self, conversation_id: str) -> list[Item]:
        """Récupère uniquement les messages d'une conversation (pas les tool calls/results)."""
        return self.get_conversation_items(conversation_id, kind="message")

    def get_item(self, item_id: str) -> Optional[Item]:
        """Récupère un item par son ID."""
        return self.session.get(Item, item_id)

    # ─────────────────────────────────────────────────────────────────────────
    # Utility methods
    # ─────────────────────────────────────────────────────────────────────────

    def get_last_conversation(self) -> Optional[Conversation]:
        """Récupère la dernière conversation."""
        stmt = (
            select(Conversation)
            .order_by(desc(Conversation.started_at))
            .limit(1)
        )
        return self.session.scalar(stmt)

    def get_conversation_summary(self, conversation_id: str) -> dict[str, Any]:
        """Génère un résumé de la conversation."""
        conversation = self.get_conversation(conversation_id)
        if not conversation:
            return {}

        items = self.get_conversation_items(conversation_id)
        
        message_count = sum(1 for i in items if i.kind == "message")
        tool_call_count = sum(1 for i in items if i.kind == "tool_call")
        
        return {
            "conversation_id": conversation.conversation_id,
            "started_at": conversation.started_at.isoformat(),
            "ended_at": conversation.ended_at.isoformat() if conversation.ended_at else None,
            "provider": conversation.provider,
            "model": conversation.model,
            "message_count": message_count,
            "tool_call_count": tool_call_count,
            "total_items": len(items),
        }
