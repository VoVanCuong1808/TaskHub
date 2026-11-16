"""Task CRUD use cases and transaction boundaries."""

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from app.core.constants import DEFAULT_PAGE_LIMIT
from app.core.exceptions import TaskNotFoundError
from app.models.enums import TaskPriority, TaskStatus, WorkspacePermission
from app.models.task import Task
from app.services.task_access import TaskAccess
from app.services.task_transaction import task_transaction
from app.services.task_uow import TaskManagementUnitOfWork

TASK_UPDATE_FIELDS = frozenset(
    {"title", "description", "status", "priority", "due_date", "assignee_id"}
)


class TaskService:
    def __init__(self, uow: TaskManagementUnitOfWork) -> None:
        self._uow = uow
        self._access = TaskAccess(uow)

    async def create(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        title: str,
        description: str = "",
        status: TaskStatus = TaskStatus.TODO,
        priority: TaskPriority = TaskPriority.MEDIUM,
        due_date: datetime | None = None,
        assignee_id: UUID | None = None,
    ) -> Task:
        async with task_transaction(self._uow):
            grant = await self._access.project(
                project_id, user_id, WorkspacePermission.TASK_CREATE, write=True
            )
            if assignee_id is not None:
                await self._access.assignee(grant.workspace, assignee_id)
            return await self._uow.tasks.add(
                Task(
                    project_id=project_id,
                    created_by=user_id,
                    title=title,
                    description=description,
                    status=status,
                    priority=priority,
                    due_date=due_date,
                    assignee_id=assignee_id,
                )
            )

    async def list(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        assignee_id: UUID | None = None,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[Task], int]:
        await self._access.project(
            project_id, user_id, WorkspacePermission.TASK_READ, write=False
        )
        return await self._uow.tasks.list(
            project_id=project_id,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            offset=offset,
            limit=limit,
        )

    async def get(self, task_id: UUID, user_id: UUID) -> Task:
        task, _ = await self._access.task(
            task_id, user_id, WorkspacePermission.TASK_READ, write=False
        )
        return task

    async def update(
        self, task_id: UUID, changes: Mapping[str, object], user_id: UUID
    ) -> Task:
        if changes.keys() - TASK_UPDATE_FIELDS:
            raise ValueError("Unsupported task fields")
        async with task_transaction(self._uow):
            task, grant = await self._access.task(
                task_id, user_id, WorkspacePermission.TASK_UPDATE, write=True
            )
            assignee_id = changes.get("assignee_id")
            if "assignee_id" in changes and assignee_id is not None:
                await self._access.assignee(grant.workspace, assignee_id)
            for attribute, value in changes.items():
                setattr(task, attribute, value)
            task.touch()
            saved = await self._uow.tasks.save(task)
            if saved is None:
                raise TaskNotFoundError(task_id)
            return saved

    async def delete(self, task_id: UUID, user_id: UUID) -> None:
        async with task_transaction(self._uow):
            await self._access.task(
                task_id, user_id, WorkspacePermission.TASK_DELETE, write=True
            )
            await self._uow.tasks.delete(task_id)
