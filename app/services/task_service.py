"""Task CRUD use cases and transaction boundaries."""

import logging
from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from app.core.constants import DEFAULT_PAGE_LIMIT
from app.core.exceptions import TaskNotFoundError
from app.models.enums import TaskPriority, TaskStatus, WorkspacePermission
from app.models.task import Task
from app.services.task_access import TaskAccess
from app.services.task_list_cache import TaskListCache, task_list_query_digest
from app.services.task_transaction import task_transaction
from app.services.task_uow import TaskManagementUnitOfWork

TASK_UPDATE_FIELDS = frozenset(
    {"title", "description", "status", "priority", "due_date", "assignee_id"}
)
logger = logging.getLogger("taskhub")


class TaskService:
    def __init__(
        self, uow: TaskManagementUnitOfWork, cache: TaskListCache | None = None
    ) -> None:
        self._uow = uow
        self._access = TaskAccess(uow)
        self._cache = cache

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
            created = await self._uow.tasks.add(
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
        await self._rotate_list_cache(project_id)
        return created

    async def list(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        status: TaskStatus | None = None,
        priority: TaskPriority | None = None,
        assignee_id: UUID | None = None,
        q: str | None = None,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[Task], int]:
        await self._access.project(
            project_id, user_id, WorkspacePermission.TASK_READ, write=False
        )
        q = q.strip().lower() if q is not None else None
        q = q or None
        query_digest = task_list_query_digest(
            q=q,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            offset=offset,
            limit=limit,
        )
        generation = None
        if self._cache is not None:
            try:
                generation = await self._cache.generation(project_id)
                cached = await self._cache.get(project_id, generation, query_digest)
                if cached is not None:
                    return cached
            except Exception:
                logger.warning(
                    "Task-list cache read failed; using database", exc_info=True
                )
                generation = None

        result = await self._uow.tasks.list(
            project_id=project_id,
            status=status,
            priority=priority,
            assignee_id=assignee_id,
            q=q,
            offset=offset,
            limit=limit,
        )
        if self._cache is not None and generation is not None:
            try:
                await self._cache.set_if_current(
                    project_id, generation, query_digest, result[0], result[1]
                )
            except Exception:
                logger.warning("Task-list cache fill failed", exc_info=True)
        return result

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
        await self._rotate_list_cache(task.project_id)
        return saved

    async def delete(self, task_id: UUID, user_id: UUID) -> None:
        async with task_transaction(self._uow):
            task, _ = await self._access.task(
                task_id, user_id, WorkspacePermission.TASK_DELETE, write=True
            )
            await self._uow.tasks.delete(task_id)
        await self._rotate_list_cache(task.project_id)

    async def _rotate_list_cache(self, project_id: UUID | None) -> None:
        if self._cache is None or project_id is None:
            return
        try:
            await self._cache.rotate(project_id)
        except Exception:
            logger.warning(
                "Task-list cache invalidation failed after commit", exc_info=True
            )
