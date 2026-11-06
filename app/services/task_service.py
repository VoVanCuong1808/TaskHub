"""Task business rules.

Services own orchestration and raise domain exceptions; they never import
FastAPI. HTTP translation lives in ``app.main``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import TypeVar
from uuid import UUID

from app.core.exceptions import TaskNotFoundError
from app.models.task import Task, TaskStatus
from app.repositories.task_repo import TaskRepository
from app.schemas.task import TaskCreate, TaskUpdate

logger = logging.getLogger("taskhub")

T = TypeVar("T")


class TaskService:
    """Orchestrates domain models; never stores or returns transport schemas."""

    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    async def _transaction(self, operation: Awaitable[T]) -> T:
        try:
            result = await operation
            await self._repository.commit()
        except Exception:
            logger.warning("Task transaction failed; rolling back")
            await self._repository.rollback()
            raise
        return result

    async def create(self, payload: TaskCreate) -> Task:
        task = Task(
            title=payload.title,
            description=payload.description,
            status=payload.status,
        )
        return await self._transaction(self._repository.add(task))

    async def list(
        self,
        *,
        status: TaskStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Task]:
        return await self._repository.list(status=status, offset=offset, limit=limit)

    async def get(self, task_id: UUID) -> Task:
        task = await self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    async def update(self, task_id: UUID, payload: TaskUpdate) -> Task:
        task = await self.get(task_id)
        changes = payload.model_dump(exclude_unset=True)
        for attribute, value in changes.items():
            setattr(task, attribute, value)
        task.touch()
        return await self._transaction(self._repository.save(task))

    async def delete(self, task_id: UUID) -> None:
        if not await self._transaction(self._repository.delete(task_id)):
            raise TaskNotFoundError(task_id)
