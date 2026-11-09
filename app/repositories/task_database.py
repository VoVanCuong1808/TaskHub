"""Async SQL repository adapted to the task domain model."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import TaskNotFoundError
from app.db.seed import DEFAULT_PROJECT_ID, DEFAULT_USER_ID
from app.models.entities import Task as TaskRow
from app.models.enums import TaskStatus
from app.models.task import Task
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[TaskRow]):
    """Persist tasks while exposing the existing domain object contract."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TaskRow)

    @staticmethod
    def _domain(row: TaskRow) -> Task:
        return Task(
            id=row.id,
            title=row.title,
            description=row.description,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def add(self, task: Task) -> Task:
        row = TaskRow(
            id=task.id,
            project_id=DEFAULT_PROJECT_ID,
            title=task.title,
            description=task.description,
            status=task.status,
            created_by=DEFAULT_USER_ID,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return self._domain(row)

    async def list(
        self,
        *,
        status: TaskStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Task], int]:
        query = select(TaskRow).order_by(TaskRow.created_at.desc(), TaskRow.id.desc())
        count_query = select(func.count()).select_from(TaskRow)
        if status is not None:
            query = query.where(TaskRow.status == status)
            count_query = count_query.where(TaskRow.status == status)
        rows = await self.session.scalars(query.offset(offset).limit(limit))
        total = await self.session.scalar(count_query) or 0
        return [self._domain(row) for row in rows], total

    async def get(self, task_id: UUID) -> Task | None:
        row = await super().get(task_id)
        return self._domain(row) if row is not None else None

    async def get_for_update(self, task_id: UUID) -> Task | None:
        row = await self.session.scalar(
            select(TaskRow).where(TaskRow.id == task_id).with_for_update()
        )
        return self._domain(row) if row is not None else None

    async def save(self, task: Task) -> Task:
        row = await super().get(task.id)
        if row is None:
            raise TaskNotFoundError(task.id)
        row.title = task.title
        row.description = task.description
        row.status = task.status
        row.updated_at = task.updated_at
        await self.session.flush()
        await self.session.refresh(row)
        return self._domain(row)

    async def delete(self, task_id: UUID) -> bool:
        row = await super().get(task_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True
