from datetime import datetime
from typing import Optional, List
from uuid import UUID

from sqlalchemy.orm import Session

from ..models import Message
from .base_repository import BaseRepository


class MessageRepository(BaseRepository[Message]):
    """
    Repository for managing Message entities.
    """

    def __init__(self, session: Session):
        super().__init__(session, Message)

    def create_message(
        self,
        run_id: UUID,
        role: str,
        content: str,
        sequence_index: Optional[int] = None,
    ) -> Message:
        """
        Create a new message in a run.

        Args:
            run_id: The ID of the run this message belongs to.
            role: The role (user, assistant, system).
            content: The message content.
            sequence_index: The sequence index. If not provided, auto-calculates.

        Returns:
            The created Message.
        """
        if sequence_index is None:
            sequence_index = self._get_next_sequence_index(run_id)

        message = Message(
            run_id=run_id,
            role=role,
            content=content,
            sequence_index=sequence_index,
            created_at=datetime.utcnow(),
        )
        return self.create(message)

    def _get_next_sequence_index(self, run_id: UUID) -> int:
        """
        Get the next sequence index for a run.

        Args:
            run_id: The ID of the run.

        Returns:
            The next sequence index.
        """
        from sqlalchemy import func

        result = (
            self.session.query(func.max(Message.sequence_index))
            .filter(Message.run_id == run_id)
            .scalar()
        )
        return (result or 0) + 1

    def get_messages_by_run(
        self,
        run_id: UUID,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> List[Message]:
        """
        Get all messages for a run, ordered by sequence index.

        Args:
            run_id: The ID of the run.
            limit: Maximum number of messages to return.
            offset: Number of messages to skip.

        Returns:
            List of messages ordered by sequence.
        """
        query = (
            self.session.query(Message)
            .filter(Message.run_id == run_id)
            .order_by(Message.sequence_index)
            .offset(offset)
        )
        if limit:
            query = query.limit(limit)
        return query.all()

    def get_messages_by_role(self, run_id: UUID, role: str) -> List[Message]:
        """
        Get all messages with a specific role in a run.

        Args:
            run_id: The ID of the run.
            role: The role to filter by.

        Returns:
            List of messages with the specified role.
        """
        return (
            self.session.query(Message)
            .filter(Message.run_id == run_id, Message.role == role)
            .order_by(Message.sequence_index)
            .all()
        )

    def get_last_message(self, run_id: UUID) -> Optional[Message]:
        """
        Get the last message in a run.

        Args:
            run_id: The ID of the run.

        Returns:
            The last message, or None if no messages exist.
        """
        return (
            self.session.query(Message)
            .filter(Message.run_id == run_id)
            .order_by(Message.sequence_index.desc())
            .first()
        )

    def get_conversation_context(
        self,
        run_id: UUID,
        last_n: int = 10,
    ) -> List[Message]:
        """
        Get the last N messages for conversation context.

        Args:
            run_id: The ID of the run.
            last_n: Number of recent messages to retrieve.

        Returns:
            List of recent messages ordered by sequence.
        """
        messages = (
            self.session.query(Message)
            .filter(Message.run_id == run_id)
            .order_by(Message.sequence_index.desc())
            .limit(last_n)
            .all()
        )
        return list(reversed(messages))

    def count_messages(self, run_id: UUID) -> int:
        """
        Count the number of messages in a run.

        Args:
            run_id: The ID of the run.

        Returns:
            The number of messages.
        """
        from sqlalchemy import func

        return (
            self.session.query(func.count(Message.id))
            .filter(Message.run_id == run_id)
            .scalar()
            or 0
        )
