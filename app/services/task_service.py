"""Task business rules.

Services own orchestration and raise domain exceptions; they never import
FastAPI. HTTP translation lives in ``app.main``.
"""

from __future__ import annotations

from uuid import UUID

from app.core.exceptions import TaskNotFoundError
from app.models.task import Task, TaskStatus
from app.repositories.task_repo import TaskRepository
from app.schemas.task import TaskCreate, TaskUpdate


class TaskService:
    def __init__(self, repository: TaskRepository) -> None:
        self._repository = repository

    def create(self, payload: TaskCreate) -> Task:
        task = Task(
            title=payload.title,
            description=payload.description,
            status=payload.status,
        )
        return self._repository.add(task)

    def list(
        self,
        *,
        status: TaskStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Task]:
        return self._repository.list(status=status, offset=offset, limit=limit)

    def get(self, task_id: UUID) -> Task:
        task = self._repository.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        return task

    def update(self, task_id: UUID, payload: TaskUpdate) -> Task:
        task = self.get(task_id)
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            if value is not None:
                setattr(task, field, value)
        task.touch()
        return self._repository.save(task)

    def delete(self, task_id: UUID) -> None:
        if not self._repository.delete(task_id):
            raise TaskNotFoundError(task_id)
