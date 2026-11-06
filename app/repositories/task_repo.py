"""Repository contract + in-memory implementation.

Swap ``InMemoryTaskRepository`` for a SQL/Redis implementation later without
touching the service or API layers.
"""

from __future__ import annotations

from threading import RLock
from typing import Protocol
from uuid import UUID

from app.models.task import Task, TaskStatus


class TaskRepository(Protocol):
    """Persistence boundary for :class:`Task` aggregates."""

    async def add(self, task: Task) -> Task: ...

    async def list(
        self,
        *,
        status: TaskStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Task]: ...

    async def get(self, task_id: UUID) -> Task | None: ...

    async def save(self, task: Task) -> Task: ...

    async def delete(self, task_id: UUID) -> bool: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class InMemoryTaskRepository:
    """Thread-safe, process-local task store (data is lost on restart)."""

    def __init__(self) -> None:
        self._items: dict[UUID, Task] = {}
        self._lock = RLock()

    async def add(self, task: Task) -> Task:
        with self._lock:
            self._items[task.id] = task
        return task

    async def list(
        self,
        *,
        status: TaskStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Task]:
        with self._lock:
            items = list(self._items.values())
        if status is not None:
            items = [task for task in items if task.status == status]
        items.sort(key=lambda task: task.created_at, reverse=True)
        return items[offset : offset + limit]

    async def get(self, task_id: UUID) -> Task | None:
        with self._lock:
            return self._items.get(task_id)

    async def save(self, task: Task) -> Task:
        with self._lock:
            self._items[task.id] = task
        return task

    async def delete(self, task_id: UUID) -> bool:
        with self._lock:
            return self._items.pop(task_id, None) is not None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None
