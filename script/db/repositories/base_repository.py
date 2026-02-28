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
