"""SQL-only persistence stores used by task management."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import DEFAULT_PAGE_LIMIT
from app.models.entities import (
    Project,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.entities import Task as TaskRow
from app.models.enums import TaskPriority, TaskStatus
from app.models.task import Task


class TaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _domain(row: TaskRow) -> Task:
        return Task(
            id=row.id,
            project_id=row.project_id,
            created_by=row.created_by,
            title=row.title,
            description=row.description,
            status=row.status,
            priority=row.priority,
            due_date=row.due_date,
            assignee_id=row.assignee_id,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    async def add(self, task: Task) -> Task:
        row = TaskRow(
            id=task.id,
            project_id=task.project_id,
            title=task.title,
            description=task.description,
            status=task.status,
            priority=task.priority,
            due_date=task.due_date,
            assignee_id=task.assignee_id,
            created_by=task.created_by,
            created_at=task.created_at,
            updated_at=task.updated_at,
        )
        self._session.add(row)
        await self._session.flush()
        await self._session.refresh(row)
        return self._domain(row)

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
        predicates = [TaskRow.project_id == project_id]
        if status is not None:
            predicates.append(TaskRow.status == status)
        if priority is not None:
            predicates.append(TaskRow.priority == priority)
        if assignee_id is not None:
            predicates.append(TaskRow.assignee_id == assignee_id)
        query = select(TaskRow).where(*predicates)
        count_query = (
            select(func.count()).select_from(TaskRow).where(*predicates)
        )
        rows = await self._session.scalars(
            query.order_by(TaskRow.created_at.desc(), TaskRow.id.desc())
            .offset(offset)
            .limit(limit)
        )
        total = await self._session.scalar(count_query) or 0
        return [self._domain(row) for row in rows], total

    async def get(self, task_id: UUID) -> Task | None:
        row = await self._session.get(TaskRow, task_id)
        return self._domain(row) if row else None

    async def get_for_update(self, task_id: UUID) -> Task | None:
        row = await self._session.scalar(
            select(TaskRow)
            .where(TaskRow.id == task_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return self._domain(row) if row else None

    async def save(self, task: Task) -> Task | None:
        row = await self._session.get(TaskRow, task.id)
        if row is None:
            return None
        row.title = task.title
        row.description = task.description
        row.status = task.status
        row.priority = task.priority
        row.due_date = task.due_date
        row.assignee_id = task.assignee_id
        row.updated_at = task.updated_at
        await self._session.flush()
        await self._session.refresh(row)
        return self._domain(row)

    async def delete(self, task_id: UUID) -> None:
        row = await self._session.get(TaskRow, task_id)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()


class TaskProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, project_id: UUID) -> Project | None:
        return await self._session.get(Project, project_id)

    async def get_for_update(self, project_id: UUID) -> Project | None:
        return await self._session.scalar(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )


class TaskWorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, workspace_id: UUID) -> Workspace | None:
        return await self._session.get(Workspace, workspace_id)

    async def get_for_update(self, workspace_id: UUID) -> Workspace | None:
        return await self._session.scalar(
            select(Workspace)
            .where(Workspace.id == workspace_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def get_member(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None:
        return await self._session.get(WorkspaceMember, (workspace_id, user_id))

    async def get_member_for_update(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None:
        return await self._session.scalar(
            select(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )


class TaskUserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_share(self, user_id: UUID) -> User | None:
        return await self._session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
