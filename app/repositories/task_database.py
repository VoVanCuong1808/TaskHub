"""Async SQL repository adapted to the task domain model."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    PermissionDeniedError,
    ProjectArchivedError,
    ProjectNotFoundError,
    TaskNotFoundError,
)
from app.models.entities import Project as ProjectRow
from app.models.entities import Task as TaskRow
from app.models.entities import Workspace, WorkspaceMember
from app.models.enums import ProjectStatus, TaskStatus, WorkspaceRole
from app.models.task import Task


class TaskRepository:
    """Persist tasks while enforcing workspace visibility at the query boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    @staticmethod
    def _domain(row: TaskRow) -> Task:
        return Task(
            id=row.id,
            project_id=row.project_id,
            created_by=row.created_by,
            title=row.title,
            description=row.description,
            status=row.status,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def _authorize_project(
        self, project_id: UUID, user_id: UUID, *, write: bool = False
    ) -> ProjectRow:
        project_query = select(ProjectRow).where(ProjectRow.id == project_id)
        if write:
            project_query = project_query.with_for_update()
        project = await self.session.scalar(
            project_query.execution_options(populate_existing=True)
        )
        if project is None:
            raise ProjectNotFoundError()
        # Writes lock task (when present), then project, workspace, membership.
        workspace_query = select(Workspace).where(Workspace.id == project.workspace_id)
        if write:
            workspace_query = workspace_query.with_for_update()
        workspace = await self.session.scalar(
            workspace_query.execution_options(populate_existing=True)
        )
        if workspace is None:
            raise ProjectNotFoundError()
        member_query = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace.id,
            WorkspaceMember.user_id == user_id,
        )
        if write:
            member_query = member_query.with_for_update()
        member = await self.session.scalar(
            member_query.execution_options(populate_existing=True)
        )
        owner = workspace.owner_id == user_id
        if not owner and member is None:
            raise ProjectNotFoundError()
        role = WorkspaceRole.OWNER if owner else member.role
        if write and project.status == ProjectStatus.ARCHIVED:
            raise ProjectArchivedError()
        if write and role == WorkspaceRole.VIEWER:
            raise PermissionDeniedError()
        return project

    async def add(self, task: Task, *, project_id: UUID, user_id: UUID) -> Task:
        await self._authorize_project(project_id, user_id, write=True)
        row = TaskRow(
            id=task.id,
            project_id=project_id,
            title=task.title,
            description=task.description,
            status=task.status,
            created_by=user_id,
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
        project_id: UUID,
        user_id: UUID,
        status: TaskStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Task], int]:
        await self._authorize_project(project_id, user_id)
        query = select(TaskRow).where(TaskRow.project_id == project_id)
        count_query = (
            select(func.count())
            .select_from(TaskRow)
            .where(TaskRow.project_id == project_id)
        )
        if status is not None:
            query = query.where(TaskRow.status == status)
            count_query = count_query.where(TaskRow.status == status)
        query = query.order_by(TaskRow.created_at.desc(), TaskRow.id.desc())
        rows = await self.session.scalars(query.offset(offset).limit(limit))
        total = await self.session.scalar(count_query) or 0
        return [self._domain(row) for row in rows], total

    async def _authorize_task(
        self, task_id: UUID, user_id: UUID, *, write: bool
    ) -> TaskRow:
        query = select(TaskRow).where(TaskRow.id == task_id)
        if write:
            query = query.with_for_update()
        row = await self.session.scalar(query.execution_options(populate_existing=True))
        if row is None:
            raise TaskNotFoundError(task_id)
        try:
            await self._authorize_project(row.project_id, user_id, write=write)
        except ProjectNotFoundError:
            raise TaskNotFoundError(task_id) from None
        return row

    async def get(self, task_id: UUID, *, user_id: UUID) -> Task:
        row = await self._authorize_task(task_id, user_id, write=False)
        return self._domain(row)

    async def get_for_update(self, task_id: UUID, *, user_id: UUID) -> Task:
        row = await self._authorize_task(task_id, user_id, write=True)
        return self._domain(row)

    async def save(self, task: Task) -> Task:
        row = await self.session.scalar(
            select(TaskRow)
            .where(TaskRow.id == task.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise TaskNotFoundError(task.id)
        row.title = task.title
        row.description = task.description
        row.status = task.status
        row.updated_at = task.updated_at
        await self.session.flush()
        await self.session.refresh(row)
        return self._domain(row)

    async def delete(self, task_id: UUID, *, user_id: UUID) -> bool:
        row = await self._authorize_task(task_id, user_id, write=True)
        await self.session.delete(row)
        await self.session.flush()
        return True
