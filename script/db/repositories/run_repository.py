from datetime import datetime
from typing import Optional, List
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from ..models import Run, Message
from ..time_utils import utc_now
from .base_repository import BaseRepository


class RunRepository(BaseRepository[Run]):
    """
    Repository for managing Run entities.
    """

    def __init__(self, session: Session):
        super().__init__(session, Run)

    def create_run(
        self,
        trigger_type: str,
        provider: str,
        model: str,
    ) -> Run:
        """
        Create a new run.

        Args:
            trigger_type: How the run was triggered.
            provider: The provider being used.
            model: The model being used.

        Returns:
            The created Run.
        """
        run = Run(
            trigger_type=trigger_type,
            provider=provider,
            model=model,
            status="running",
            started_at=utc_now(),
        )
        return self.create(run)

    def complete_run(
        self,
        run_id: UUID,
        status: str = "completed",
    ) -> Optional[Run]:
        """
        Mark a run as completed.

        Args:
            run_id: The ID of the run.
            status: Final status (completed, failed, cancelled).

        Returns:
            The updated Run, or None if not found.
        """
        run = self.get_by_id(run_id)
        if run:
            run.status = status
            run.ended_at = utc_now()
            self.session.flush()
        return run

    def get_filtered_runs(
            self,
            trigger_type: Optional[str] = None,
            status: Optional[str] = None,
            before: Optional[datetime] = None,
            after: Optional[datetime] = None,
            limit: Optional[int] = None
        ) -> List[Run]:
        """
        Get runs with optional time filtering.
        Args:
            trigger_type: If provided, filters runs by trigger_type.
            before: If provided, only runs started before this time are returned.
            after: If provided, only runs started after this time are returned.
            limit: If provided, limits the number of runs returned.

        Returns:
            List of runs matching the filters.
        """
        query = (
            self.session.query(Run)
            .order_by(Run.started_at.desc())
        )

        if trigger_type:
            query = query.filter(Run.trigger_type == trigger_type)
        if status:
            query = query.filter(Run.status == status)
        if before:
            query = query.filter(Run.started_at <= before)
        if after:
            query = query.filter(Run.started_at >= after)
        if limit:
            query = query.limit(limit)
        
        return query.all()

    def get_run_with_details(self, run_id: UUID) -> Optional[Run]:
        """
        Get a run with messages and nested tool calls eagerly loaded.

        Args:
            run_id: The ID of the run.

        Returns:
            The run if found, otherwise None.
        """
        return (
            self.session.query(Run)
            .options(
                selectinload(Run.messages).selectinload(Message.tool_calls),
            )
            .filter(Run.id == run_id)
            .first()
        )
