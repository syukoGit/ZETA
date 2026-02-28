"""
Repository for Run operations.
"""

from datetime import datetime, timezone
from typing import Optional, List
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm import selectinload

from ..models import Run, Message
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
            started_at=datetime.now(timezone.utc),
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
            run.ended_at = datetime.now(timezone.utc)
            self.session.flush()
        return run

    def get_active_runs(self) -> List[Run]:
        """
        Get all currently active (running) runs.

        Returns:
            List of active runs.
        """
        return (
            self.session.query(Run)
            .filter(Run.status == "running")
            .order_by(Run.started_at.desc())
            .all()
        )
    
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

    def get_runs_by_status(self, status: str) -> List[Run]:
        """
        Get all runs with a specific status.

        Args:
            status: The status to filter by.

        Returns:
            List of runs with the specified status.
        """
        return (
            self.session.query(Run)
            .filter(Run.status == status)
            .order_by(Run.started_at.desc())
            .all()
        )

    def get_recent_runs(self, limit: int = 10) -> List[Run]:
        """
        Get the most recent runs.

        Args:
            limit: Maximum number of runs to return.

        Returns:
            List of recent runs.
        """
        return (
            self.session.query(Run)
            .order_by(Run.started_at.desc())
            .limit(limit)
            .all()
        )

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

    def get_runs_by_objective_contains(self, search_term: str) -> List[Run]:
        """
        Search runs by objective.

        Args:
            search_term: Term to search for in objectives.

        Returns:
            List of matching runs.
        """
        return (
            self.session.query(Run)
            .filter(Run.objective.ilike(f"%{search_term}%"))
            .order_by(Run.started_at.desc())
            .all()
        )
