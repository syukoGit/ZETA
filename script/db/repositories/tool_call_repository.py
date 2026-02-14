"""
Repository for ToolCall operations.
"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID

from sqlalchemy.orm import Session

from ..models import ToolCall
from .base_repository import BaseRepository


class ToolCallRepository(BaseRepository[ToolCall]):

    def __init__(self, session: Session):
        super().__init__(session, ToolCall)

    def create_tool_call(
        self,
        message_id: UUID,
        tool_name: str,
        input_payload: Optional[dict] = None,
        status: str = "pending",
    ) -> ToolCall:
        """
        Create a new tool call.

        Args:
            message_id: The ID of the message that triggered this call.
            tool_name: Name of the tool being called.
            input_payload: Input parameters for the tool.
            status: Initial status (pending, running, completed, failed).

        Returns:
            The created ToolCall.
        """
        tool_call = ToolCall(
            message_id=message_id,
            tool_name=tool_name,
            input_payload=input_payload,
            status=status,
            executed_at=datetime.utcnow(),
        )
        return self.create(tool_call)

    def complete_tool_call(
        self,
        tool_call_id: UUID,
        output_payload: Optional[dict] = None,
        status: str = "completed",
    ) -> Optional[ToolCall]:
        """
        Mark a tool call as completed.

        Args:
            tool_call_id: The ID of the tool call.
            output_payload: The output from the tool.
            status: Final status (completed, failed).

        Returns:
            The updated ToolCall, or None if not found.
        """
        tool_call = self.get_by_id(tool_call_id)
        if tool_call:
            tool_call.output_payload = output_payload
            tool_call.status = status
            self.session.flush()
        return tool_call

    def get_tool_calls_by_message(self, message_id: UUID) -> List[ToolCall]:
        """
        Get all tool calls for a message.

        Args:
            message_id: The ID of the message.

        Returns:
            List of tool calls for the message.
        """
        return (
            self.session.query(ToolCall)
            .filter(ToolCall.message_id == message_id)
            .order_by(ToolCall.executed_at)
            .all()
        )

    def get_tool_calls_by_name(
        self,
        tool_name: str,
        limit: int = 50,
    ) -> List[ToolCall]:
        """
        Get all calls to a specific tool.

        Args:
            tool_name: The name of the tool.
            limit: Maximum number of results.

        Returns:
            List of tool calls.
        """
        return (
            self.session.query(ToolCall)
            .filter(ToolCall.tool_name == tool_name)
            .order_by(ToolCall.executed_at.desc())
            .limit(limit)
            .all()
        )

    def get_failed_tool_calls(self, limit: int = 50) -> List[ToolCall]:
        """
        Get recent failed tool calls.

        Args:
            limit: Maximum number of results.

        Returns:
            List of failed tool calls.
        """
        return (
            self.session.query(ToolCall)
            .filter(ToolCall.status == "failed")
            .order_by(ToolCall.executed_at.desc())
            .limit(limit)
            .all()
        )

    def get_tool_call_stats(self) -> dict:
        """
        Get statistics about tool calls.

        Returns:
            Dictionary with tool call statistics.
        """
        from sqlalchemy import func

        stats = (
            self.session.query(
                ToolCall.tool_name,
                ToolCall.status,
                func.count(ToolCall.id).label("count"),
            )
            .group_by(ToolCall.tool_name, ToolCall.status)
            .all()
        )

        result = {}
        for tool_name, status, count in stats:
            if tool_name not in result:
                result[tool_name] = {}
            result[tool_name][status] = count

        return result
