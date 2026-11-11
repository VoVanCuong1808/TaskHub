"""Repository protocol and in-memory implementation for isolated tests."""

from __future__ import annotations

from threading import RLock
from typing import Protocol
from uuid import UUID

from app.core.exceptions import TaskNotFoundError
from app.models.enums import TaskStatus
from app.models.task import Task


class TaskRepositoryProtocol(Protocol):
    """Persistence boundary for :class:`Task` aggregates."""

    async def add(self, task: Task, *, project_id: UUID, user_id: UUID) -> Task: ...

    async def list(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        status: TaskStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Task], int]: ...

    async def get(self, task_id: UUID, *, user_id: UUID) -> Task | None: ...

    async def get_for_update(
        self, task_id: UUID, *, user_id: UUID
    ) -> Task | None: ...

    async def save(self, task: Task) -> Task: ...

    async def delete(self, task_id: UUID, *, user_id: UUID) -> bool: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class InMemoryTaskRepository:
    """Thread-safe, process-local task store (data is lost on restart)."""

    def __init__(self) -> None:
        self._items: dict[UUID, Task] = {}
        self._lock = RLock()

    async def add(self, task: Task, *, project_id: UUID, user_id: UUID) -> Task:
        task.project_id = project_id
        task.created_by = user_id
        with self._lock:
            self._items[task.id] = task
        return task

    async def list(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        status: TaskStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Task], int]:
        with self._lock:
            items = [
                task for task in self._items.values() if task.project_id == project_id
            ]
        if status is not None:
            items = [task for task in items if task.status == status]
        items.sort(key=lambda task: task.created_at, reverse=True)
        total = len(items)
        return items[offset : offset + limit], total

    async def get(self, task_id: UUID, *, user_id: UUID) -> Task | None:
        with self._lock:
            return self._items.get(task_id)

    async def get_for_update(self, task_id: UUID, *, user_id: UUID) -> Task:
        task = await self.get(task_id, user_id=user_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    async def save(self, task: Task) -> Task:
        with self._lock:
            self._items[task.id] = task
        return task

    async def delete(self, task_id: UUID, *, user_id: UUID) -> bool:
        with self._lock:
            return self._items.pop(task_id, None) is not None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None
