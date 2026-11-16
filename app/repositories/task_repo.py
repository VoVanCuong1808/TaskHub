"""Process-local task persistence used by isolated unit tests."""

from __future__ import annotations

from threading import RLock
from uuid import UUID

from app.core.constants import DEFAULT_PAGE_LIMIT
from app.models.enums import TaskPriority, TaskStatus
from app.models.task import Task


class InMemoryTaskRepository:
    """A small persistence-only TaskStore; data is lost on restart."""

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
        project_id: UUID,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        assignee_id: UUID | None = None,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[Task], int]:
        with self._lock:
            items = [
                task for task in self._items.values() if task.project_id == project_id
            ]
        if status is not None:
            items = [task for task in items if task.status == status]
        if priority is not None:
            items = [task for task in items if task.priority == priority]
        if assignee_id is not None:
            items = [task for task in items if task.assignee_id == assignee_id]
        items.sort(key=lambda task: (task.created_at, task.id), reverse=True)
        return items[offset : offset + limit], len(items)

    async def get(self, task_id: UUID) -> Task | None:
        with self._lock:
            return self._items.get(task_id)

    async def get_for_update(self, task_id: UUID) -> Task | None:
        return await self.get(task_id)

    async def save(self, task: Task) -> Task | None:
        with self._lock:
            self._items[task.id] = task
        return task

    async def delete(self, task_id: UUID) -> None:
        with self._lock:
            self._items.pop(task_id, None)
