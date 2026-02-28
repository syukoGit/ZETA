from typing import Optional, List
from uuid import UUID

from sqlalchemy.orm import Session

from ..models import ToolCall
from ..time_utils import utc_now
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
            executed_at=utc_now(),
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
