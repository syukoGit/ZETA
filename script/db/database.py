import os
from contextlib import contextmanager
from typing import Generator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .models import Base


class DatabaseManager:
    """
    Manages database connections and sessions.
    """

    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize the database manager.

        Args:
            connection_string: PostgreSQL connection string.
                             If not provided, uses DATABASE_URL environment variable.
        """
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self.engine = create_engine(
            self.connection_string,
            echo=False,
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=10,
        )
        self.SessionLocal = sessionmaker(
            bind=self.engine,
            autocommit=False,
            autoflush=False,
            expire_on_commit=False,
        )

    def create_tables(self) -> None:
        """Create all tables in the database."""
        Base.metadata.create_all(bind=self.engine)

    def drop_tables(self) -> None:
        """Drop all tables in the database. Use with caution!"""
        Base.metadata.drop_all(bind=self.engine)

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """
        Provide a transactional scope around a series of operations.

        Yields:
            Session: A SQLAlchemy session.
        """
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def get_session_instance(self) -> Session:
        """
        Get a new session instance. Caller is responsible for closing it.

        Returns:
            Session: A new SQLAlchemy session.
        """
        return self.SessionLocal()


# Global database manager instance
_db_manager: Optional[DatabaseManager] = None


def init_db(connection_string: Optional[str] = None) -> DatabaseManager:
    """
    Initialize the global database manager.

    Args:
        connection_string: PostgreSQL connection string.

    Returns:
        DatabaseManager: The initialized database manager.
    """
    global _db_manager
    _db_manager = DatabaseManager(connection_string)
    return _db_manager


def get_db() -> DatabaseManager:
    """
    Get the global database manager instance.

    Returns:
        DatabaseManager: The global database manager.

    Raises:
        RuntimeError: If the database has not been initialized.
    """
    if _db_manager is None:
        # Auto-initialize with default settings
        return init_db()
    return _db_manager
