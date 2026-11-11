"""Task business rules.

Services own orchestration and raise domain exceptions; they never import
FastAPI. HTTP translation lives in ``app.main``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import TypeVar
from uuid import UUID

from app.models.enums import TaskStatus
from app.models.task import Task
from app.repositories.task_repo import TaskRepositoryProtocol
from app.schemas.task import TaskCreate, TaskUpdate

logger = logging.getLogger("taskhub")

T = TypeVar("T")


class TaskService:
    """Orchestrates domain models; never stores or returns transport schemas."""

    def __init__(self, repository: TaskRepositoryProtocol) -> None:
        self._repository = repository

    async def _transaction(self, operation: Awaitable[T]) -> T:
        try:
            result = await operation
            await self._repository.commit()
        except BaseException:
            logger.warning("Task transaction failed; rolling back")
            await self._repository.rollback()
            raise
        return result

    async def create(self, payload: TaskCreate, user_id: UUID) -> Task:
        task = Task(
            title=payload.title,
            description=payload.description,
            status=payload.status,
        )
        return await self._transaction(
            self._repository.add(task, project_id=payload.project_id, user_id=user_id)
        )

    async def list(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        status: TaskStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Task], int]:
        return await self._repository.list(
            project_id=project_id,
            user_id=user_id,
            status=status,
            offset=offset,
            limit=limit,
        )

    async def get(self, task_id: UUID, user_id: UUID) -> Task:
        return await self._repository.get(task_id, user_id=user_id)

    async def update(self, task_id: UUID, payload: TaskUpdate, user_id: UUID) -> Task:
        async def operation() -> Task:
            task = await self._repository.get_for_update(task_id, user_id=user_id)
            for attribute, value in payload.model_dump(exclude_unset=True).items():
                setattr(task, attribute, value)
            task.touch()
            return await self._repository.save(task)

        return await self._transaction(operation())

    async def delete(self, task_id: UUID, user_id: UUID) -> None:
        await self._transaction(self._repository.delete(task_id, user_id=user_id))
