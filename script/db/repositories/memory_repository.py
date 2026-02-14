from typing import Optional, List, Tuple, Dict, Any

from sqlalchemy.orm import Session

from ..models import MemoryEntry
from .base_repository import BaseRepository


class MemoryRepository(BaseRepository[MemoryEntry]):
    """
    Repository for managing MemoryEntry entities with vector search capabilities.
    """

    def __init__(self, session: Session):
        super().__init__(session, MemoryEntry)

    def search_by_embedding(
        self,
        query_embedding: List[float],
        limit: int = 5,
        memory_types: Optional[List[str]] = None,
        status: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        meta_filters: Optional[Dict[str, Any]] = None,
        min_similarity: float = 0.5,
    ) -> List[Tuple[MemoryEntry, float]]:
        """
        Search memory entries using vector similarity and structured filters.

        Args:
            query_embedding: Embedding vector for the query.
            limit: Maximum number of results.
            memory_types: Optional list of memory types to include.
            status: Optional list of statuses to include.
            tags: Optional list of tags; entry must overlap at least one.
            meta_filters: Optional JSON filters that must match exactly.
            min_similarity: Minimum cosine similarity threshold.

        Returns:
            List of (MemoryEntry, similarity) tuples.
        """
        similarity_expr = 1 - MemoryEntry.embedding.cosine_distance(query_embedding)

        query = self.session.query(MemoryEntry, similarity_expr.label("similarity"))
        query = query.filter(MemoryEntry.embedding.is_not(None))

        if memory_types:
            query = query.filter(MemoryEntry.memory_type.in_(memory_types))

        if status:
            query = query.filter(MemoryEntry.status.in_(status))

        if tags:
            query = query.filter(MemoryEntry.tags.overlap(tags))

        if meta_filters:
            query = query.filter(MemoryEntry.meta.contains(meta_filters))

        if min_similarity is not None:
            query = query.filter(similarity_expr >= min_similarity)

        query = query.order_by(similarity_expr.desc()).limit(limit)

        results = query.all()
        return [(entry, similarity) for entry, similarity in results]
