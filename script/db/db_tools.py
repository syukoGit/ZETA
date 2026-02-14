from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Union
from uuid import UUID

from .database import get_db
from .models import MemoryAccessLog, MemoryEntry
from .repositories import (
    RunRepository,
    MessageRepository,
    ToolCallRepository,
    MemoryRepository,
)


class DBTools:
    """
    Tools for the cognitive agent to interact with the memory system.
    All memory access is logged and traced to the originating message.
    """
    _instance: Optional["DBTools"] = None
    embedding_function: Any

    def __new__(cls, embedding_function=None):
        if cls._instance is None:
            cls._instance = super(DBTools, cls).__new__(cls)
            cls._instance.embedding_function = embedding_function
        return cls._instance

    @classmethod
    def get_instance(cls) -> "DBTools":
        if cls._instance is None:
            raise RuntimeError("DBTools has not been initialized. Call DBTools(embedding_function=...) first.")
        return cls._instance

    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Generate an embedding for the given text."""
        if self.embedding_function:
            return self.embedding_function(text)
        return None

    # ========== Run Management Tools ==========

    def start_run(
        self,
        trigger_type: str,
        provider: str,
        model: str,
    ) -> UUID:
        """
        Start a new run.

        Args:
            trigger_type: How the run was triggered.
            provider: The provider being used.
            model: The model being used.

        Returns:
            The ID of the created run.
        """
        db = get_db()
        with db.get_session() as session:
            run_repo = RunRepository(session)
            run = run_repo.create_run(
                trigger_type=trigger_type,
                provider=provider,
                model=model,
            )
            return run.id

    def end_run(
        self,
        run_id: UUID,
        status: str = "completed",
    ) -> bool:
        """
        End a run.

        Args:
            run_id: The ID of the run to end.
            status: Final status (completed, failed, cancelled).
            final_output: The final output of the run.

        Returns:
            True if successful, False if run not found.
        """
        db = get_db()
        with db.get_session() as session:
            run_repo = RunRepository(session)
            run = run_repo.complete_run(run_id, status)
            return run is not None

    # ========== Message Tools ==========

    def add_message(
        self,
        run_id: UUID,
        role: str,
        content: str,
    ) -> UUID:
        """
        Add a message to a run.

        Args:
            run_id: The ID of the run.
            role: The role (user, assistant, system).
            content: The message content.

        Returns:
            The ID of the created message.
        """
        db = get_db()
        with db.get_session() as session:
            message_repo = MessageRepository(session)
            message = message_repo.create_message(
                run_id=run_id,
                role=role,
                content=content,
            )
            return message.id

    def get_conversation_history(
        self,
        run_id: UUID,
        last_n: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Get recent conversation history for a run.

        Args:
            run_id: The ID of the run.
            last_n: Number of recent messages to retrieve.

        Returns:
            List of message dictionaries.
        """
        db = get_db()
        with db.get_session() as session:
            message_repo = MessageRepository(session)
            messages = message_repo.get_conversation_context(run_id, last_n)
            return [
                {
                    "id": str(msg.id),
                    "role": msg.role,
                    "content": msg.content,
                    "sequence_index": msg.sequence_index,
                    "created_at": msg.created_at.isoformat() if msg.created_at else None,
                }
                for msg in messages
            ]

    # ========== Tool Call Logging ==========

    def log_tool_call(
        self,
        message_id: UUID,
        tool_name: str,
        input_payload: dict,
    ) -> UUID:
        """
        Log a tool call initiation.

        Args:
            message_id: The ID of the message that triggered the call.
            tool_name: Name of the tool.
            input_payload: Input parameters.

        Returns:
            The ID of the created tool call record.
        """
        db = get_db()
        with db.get_session() as session:
            tool_repo = ToolCallRepository(session)
            tool_call = tool_repo.create_tool_call(
                message_id=message_id,
                tool_name=tool_name,
                input_payload=input_payload,
                status="running",
            )
            return tool_call.id

    def complete_tool_call(
        self,
        tool_call_id: UUID,
        output_payload: dict,
        success: bool = True,
    ) -> bool:
        """
        Mark a tool call as completed.

        Args:
            tool_call_id: The ID of the tool call.
            output_payload: The tool's output.
            success: Whether the call succeeded.

        Returns:
            True if successful, False if tool call not found.
        """
        db = get_db()
        with db.get_session() as session:
            tool_repo = ToolCallRepository(session)
            tool_call = tool_repo.complete_tool_call(
                tool_call_id=tool_call_id,
                output_payload=output_payload,
                status="completed" if success else "failed",
            )
            return tool_call is not None

    # ========== Memory Search Tools ==========

    def search_memory(
        self,
        query: str,
        message_id: UUID,
        limit: int = 5,
        memory_types: Optional[List[str]] = None,
        status: Optional[List[str]] = None,
        tags: Optional[List[str]] = None,
        meta_filters: Optional[Dict[str, Any]] = None,
        min_similarity: float = 0.5,
    ) -> List[Dict[str, Any]]:
        """
        Search memory using semantic similarity and structured filters.

        Args:
            query: Free text query to search for.
            message_id: The ID of the message initiating the search.
            limit: Maximum number of results.
            memory_types: Optional list of memory types to include.
            status: Optional status or list of statuses to include.
            tags: Optional list of tags; entry must overlap at least one.
            meta_filters: Optional JSON filters that must match exactly.
            min_similarity: Minimum cosine similarity threshold.

        Returns:
            List of memory search result dictionaries.
        """
        if not query or not query.strip():
            return []

        query_embedding = self._get_embedding(query)
        if query_embedding is None:
            return []

        allowed_statuses: Optional[List[str]]
        if status is None:
            allowed_statuses = ["active"]
        elif isinstance(status, list):
            allowed_statuses = status
        else:
            allowed_statuses = [status]

        db = get_db()
        with db.get_session() as session:
            memory_repo = MemoryRepository(session)
            results = memory_repo.search_by_embedding(
                query_embedding=query_embedding,
                limit=limit,
                memory_types=memory_types,
                status=allowed_statuses,
                tags=tags,
                meta_filters=meta_filters,
                min_similarity=min_similarity,
            )

            response: List[Dict[str, Any]] = []
            for memory, similarity in results:
                access_log = MemoryAccessLog(
                    message_id=message_id,
                    memory_id=memory.id,
                    access_type="read",
                    reason="search_memory",
                )
                session.add(access_log)

                response.append(
                    {
                        "id": memory.id,
                        "title": memory.title,
                        "content": memory.content or "",
                        "memory_type": memory.memory_type or "",
                        "similarity": float(similarity),
                        "tags": memory.tags or [],
                        "created_at": memory.created_at,
                    }
                )

            return response

    def memory_get_by_id(
        self,
        memory_id: UUID,
        message_id: UUID,
    ) -> Dict[str, Any]:
        """
        Retrieve a memory entry by its ID.

        Args:
            memory_id: The ID of the memory entry.

        Returns:
            A dictionary with memory details, or None if not found.
        """
        db = get_db()
        with db.get_session() as session:
            memory_repo = MemoryRepository(session)
            memory = memory_repo.get_by_id(memory_id)
            if not memory:
                return {}
            
            access_log = MemoryAccessLog(
                message_id=message_id,
                memory_id=memory.id,
                access_type="read",
                reason="memory_get_by_id",
            )
            session.add(access_log)

            return {
                "id": memory.id,
                "title": memory.title,
                "content": memory.content or "",
                "memory_type": memory.memory_type or "",
                "tags": memory.tags or [],
                "created_at": memory.created_at,
            }

    # ========== Memory Write Tools ==========

    def memory_create(
        self,
        content: str,
        memory_type: str,
        title: str,
        message_id: UUID,
        source: Optional[str] = None,
        tags: Optional[List[str]] = None,
        meta: Optional[Dict[str, Any]] = None,
        status: str = "active",
    ) -> Dict[str, Any]:
        """
        Create a new memory entry with mandatory embedding.

        Args:
            content: Memory content.
            memory_type: Type/category of memory.
            title: title.
            message_id: Message ID to log the write access.
            source: Optional source of the memory.
            tags: Optional list of tags.
            meta: Optional metadata dictionary.
            status: Memory status.

        Returns:
            A dictionary representing the created memory.
        """
        if not content or not content.strip():
            raise ValueError("content is required")
        if not memory_type or not memory_type.strip():
            raise ValueError("memory_type is required")

        embedding = self._get_embedding(content)
        if embedding is None:
            raise RuntimeError("embedding_function is required to create memory")

        db = get_db()
        with db.get_session() as session:
            memory = MemoryEntry(
                content=content,
                memory_type=memory_type,
                title=title,
                source=source,
                tags=tags or [],
                meta=meta,
                status=status,
                embedding=embedding,
            )
            session.add(memory)
            session.flush()

            access_log = MemoryAccessLog(
                message_id=message_id,
                memory_id=memory.id,
                access_type="write",
                reason="memory_create",
            )
            session.add(access_log)

            return {
                "id": memory.id,
                "memory_type": memory.memory_type,
                "title": memory.title,
                "content": memory.content or "",
                "status": memory.status,
                "source": memory.source,
                "tags": memory.tags or [],
                "metadata": memory.meta,
                "created_at": memory.created_at,
                "updated_at": memory.updated_at,
            }

    def memory_update(
        self,
        memory_id: UUID,
        message_id: UUID,
        reason: str,
        content: Optional[str] = None,
        meta: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Update an existing memory entry while logging the change.

        Args:
            memory_id: The ID of the memory entry.
            message_id: The ID of the message initiating the update.
            reason: Explicit reason for the modification.
            content: Optional new content.
            meta: Optional new metadata.
            status: Optional new status.
            tags: Optional new tags.

        Returns:
            A dictionary with updated memory details, or empty dict if not found.
        """
        if message_id is None:
            raise ValueError("message_id is required")
        if not reason or not reason.strip():
            raise ValueError("reason is required")

        if content is None and meta is None and status is None and tags is None:
            raise ValueError("at least one field must be provided to update")

        if content is not None and not content.strip():
            raise ValueError("content cannot be empty when provided")

        db = get_db()
        with db.get_session() as session:
            memory_repo = MemoryRepository(session)
            memory = memory_repo.get_by_id(memory_id)
            if not memory:
                return {}

            if content is not None:
                embedding = self._get_embedding(content)
                if embedding is None:
                    raise RuntimeError("embedding_function is required to update content")
                memory.content = content
                memory.embedding = embedding

            if meta is not None:
                memory.meta = meta

            if status is not None:
                memory.status = status

            if tags is not None:
                memory.tags = tags

            access_log = MemoryAccessLog(
                message_id=message_id,
                memory_id=memory.id,
                access_type="update",
                reason=reason,
            )
            session.add(access_log)
            session.flush()

            return {
                "id": memory.id,
                "memory_type": memory.memory_type,
                "title": memory.title,
                "content": memory.content or "",
                "status": memory.status,
                "source": memory.source,
                "tags": memory.tags or [],
                "metadata": memory.meta,
                "created_at": memory.created_at,
                "updated_at": memory.updated_at,
            }
    
    # ========== Introspection Tools ==========

    def memory_deprecate(
        self,
        memory_id: UUID,
        message_id: UUID,
        reason: str,
    ) -> Dict[str, Any]:
        """
        Deprecate a memory entry while logging the change.

        Args:
            memory_id: The ID of the memory entry.
            message_id: The ID of the message initiating the deprecation.
            reason: Explicit reason for the deprecation.

        Returns:
            A dictionary with updated memory details, or empty dict if not found.
        """
        if message_id is None:
            raise ValueError("message_id is required")
        if not reason or not reason.strip():
            raise ValueError("reason is required")

        db = get_db()
        with db.get_session() as session:
            memory_repo = MemoryRepository(session)
            memory = memory_repo.get_by_id(memory_id)
            if not memory:
                return {}

            memory.status = "deprecated"

            access_log = MemoryAccessLog(
                message_id=message_id,
                memory_id=memory.id,
                access_type="deprecate",
                reason=reason,
            )
            session.add(access_log)
            session.flush()

            return {
                "id": memory.id,
                "memory_type": memory.memory_type,
                "title": memory.title,
                "content": memory.content or "",
                "status": memory.status,
                "source": memory.source,
                "tags": memory.tags or [],
                "metadata": memory.meta,
                "created_at": memory.created_at,
                "updated_at": memory.updated_at,
            }