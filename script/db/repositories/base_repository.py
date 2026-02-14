"""
Base repository with common CRUD operations.
"""

from typing import TypeVar, Generic, Optional, List, Type
from uuid import UUID

from sqlalchemy.orm import Session

from ..models import Base

T = TypeVar("T", bound=Base)


class BaseRepository(Generic[T]):
    """
    Base repository providing common CRUD operations.
    """

    def __init__(self, session: Session, model_class: Type[T]):
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy session.
            model_class: The model class this repository manages.
        """
        self.session = session
        self.model_class = model_class

    def get_by_id(self, id: UUID) -> Optional[T]:
        """
        Get an entity by its ID.

        Args:
            id: The UUID of the entity.

        Returns:
            The entity if found, None otherwise.
        """
        return self.session.query(self.model_class).filter(self.model_class.id == id).first()

    def get_all(self, limit: Optional[int] = None, offset: int = 0) -> List[T]:
        """
        Get all entities with optional pagination.

        Args:
            limit: Maximum number of entities to return.
            offset: Number of entities to skip.

        Returns:
            List of entities.
        """
        query = self.session.query(self.model_class).offset(offset)
        if limit:
            query = query.limit(limit)
        return query.all()

    def create(self, entity: T) -> T:
        """
        Create a new entity.

        Args:
            entity: The entity to create.

        Returns:
            The created entity.
        """
        self.session.add(entity)
        self.session.flush()
        return entity

    def update(self, entity: T) -> T:
        """
        Update an existing entity.

        Args:
            entity: The entity to update.

        Returns:
            The updated entity.
        """
        self.session.merge(entity)
        self.session.flush()
        return entity

    def delete(self, entity: T) -> None:
        """
        Delete an entity.

        Args:
            entity: The entity to delete.
        """
        self.session.delete(entity)
        self.session.flush()

    def delete_by_id(self, id: UUID) -> bool:
        """
        Delete an entity by its ID.

        Args:
            id: The UUID of the entity to delete.

        Returns:
            True if the entity was deleted, False if not found.
        """
        entity = self.get_by_id(id)
        if entity:
            self.delete(entity)
            return True
        return False
