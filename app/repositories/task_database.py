"""Async SQL repository adapted to the task domain model."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    Project,
    ProjectStatus,
    User,
    UserRole,
    Workspace,
)
from app.models.entities import (
    Task as TaskRow,
)
from app.models.task import Task, TaskStatus
from app.repositories.base import BaseRepository


class TaskRepository(BaseRepository[TaskRow]):
    """Persist tasks while exposing the existing domain object contract."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, TaskRow)

    async def _default_project(self) -> tuple[UUID, UUID]:
        user = await self.session.scalar(
            select(User).where(User.email == "system@taskhub.local")
        )
        if user is None:
            user = User(
                email="system@taskhub.local", name="TaskHub System", role=UserRole.ADMIN
            )
            self.session.add(user)
            await self.session.flush()
        workspace = await self.session.scalar(
            select(Workspace).where(
                Workspace.owner_id == user.id, Workspace.name == "Default"
            )
        )
        if workspace is None:
            workspace = Workspace(name="Default", owner_id=user.id)
            self.session.add(workspace)
            await self.session.flush()
        project = await self.session.scalar(
            select(Project).where(
                Project.workspace_id == workspace.id, Project.name == "Default"
            )
        )
        if project is None:
            project = Project(
                workspace_id=workspace.id, name="Default", status=ProjectStatus.ACTIVE
            )
            self.session.add(project)
            await self.session.flush()
        return project.id, user.id

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
        project_id, user_id = await self._default_project()
        row = TaskRow(
            id=task.id,
            project_id=project_id,
            title=task.title,
            description=task.description,
            status=task.status,
            created_by_id=user_id,
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
    ) -> list[Task]:
        query = select(TaskRow).order_by(TaskRow.created_at.desc())
        if status is not None:
            query = query.where(TaskRow.status == status)
        rows = await self.session.scalars(query.offset(offset).limit(limit))
        return [self._domain(row) for row in rows]

    async def get(self, task_id: UUID) -> Task | None:
        row = await super().get(task_id)
        return self._domain(row) if row is not None else None

    async def save(self, task: Task) -> Task:
        row = await super().get(task.id)
        if row is None:
            return task
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
