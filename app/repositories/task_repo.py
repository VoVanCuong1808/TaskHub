"""Repository protocol and in-memory implementation for isolated tests."""

from __future__ import annotations

from threading import RLock
from typing import Protocol
from uuid import UUID

from app.core.exceptions import ProjectNotFoundError, TaskNotFoundError
from app.models.enums import (
    ProjectStatus,
    TaskStatus,
    WorkspacePermission,
    WorkspaceRole,
)
from app.models.task import Task
from app.services.task_authorization import (
    TaskAuthorizationContext,
    authorize_task_access,
)


class TaskRepositoryProtocol(Protocol):
    """Persistence boundary for :class:`Task` aggregates."""

    async def add(self, task: Task, *, project_id: UUID, user_id: UUID) -> Task: ...

    async def list(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        status: TaskStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Task], int]: ...

    async def get(self, task_id: UUID, *, user_id: UUID) -> Task: ...

    async def get_for_update(
        self, task_id: UUID, *, user_id: UUID
    ) -> Task: ...

    async def save(self, task: Task) -> Task: ...

    async def delete(self, task_id: UUID, *, user_id: UUID) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class InMemoryTaskRepository:
    """Thread-safe, process-local task store (data is lost on restart)."""

    def __init__(self) -> None:
        self._items: dict[UUID, Task] = {}
        self._project_access: dict[
            UUID, tuple[UUID, ProjectStatus, dict[UUID, WorkspaceRole]]
        ] = {}
        self._lock = RLock()

    def register_project(
        self,
        project_id: UUID,
        owner_id: UUID,
        *,
        status: ProjectStatus = ProjectStatus.ACTIVE,
        members: dict[UUID, WorkspaceRole] | None = None,
    ) -> None:
        """Register explicit workspace context before using this test repository."""
        with self._lock:
            self._project_access[project_id] = (
                owner_id,
                status,
                dict(members or {}),
            )

    def _authorize_project(
        self, project_id: UUID, user_id: UUID, permission: WorkspacePermission
    ) -> None:
        with self._lock:
            access = self._project_access.get(project_id)
            if access is None:
                raise ProjectNotFoundError()
            owner_id, status, members = access
            member_role = members.get(user_id)
        authorize_task_access(
            TaskAuthorizationContext(status, owner_id, member_role),
            user_id,
            permission,
        )

    def _authorize_task(
        self, task_id: UUID, user_id: UUID, permission: WorkspacePermission
    ) -> Task:
        with self._lock:
            task = self._items.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        try:
            self._authorize_project(task.project_id, user_id, permission)
        except ProjectNotFoundError:
            raise TaskNotFoundError(task_id) from None
        return task

    async def add(self, task: Task, *, project_id: UUID, user_id: UUID) -> Task:
        self._authorize_project(project_id, user_id, WorkspacePermission.TASK_CREATE)
        task.project_id = project_id
        task.created_by = user_id
        with self._lock:
            self._items[task.id] = task
        return task

    async def list(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        status: TaskStatus | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[Task], int]:
        self._authorize_project(project_id, user_id, WorkspacePermission.TASK_READ)
        with self._lock:
            items = [
                task for task in self._items.values() if task.project_id == project_id
            ]
        if status is not None:
            items = [task for task in items if task.status == status]
        items.sort(key=lambda task: task.created_at, reverse=True)
        total = len(items)
        return items[offset : offset + limit], total

    async def get(self, task_id: UUID, *, user_id: UUID) -> Task:
        return self._authorize_task(task_id, user_id, WorkspacePermission.TASK_READ)

    async def get_for_update(self, task_id: UUID, *, user_id: UUID) -> Task:
        return self._authorize_task(
            task_id, user_id, WorkspacePermission.TASK_UPDATE
        )

    async def save(self, task: Task) -> Task:
        with self._lock:
            self._items[task.id] = task
        return task

    async def delete(self, task_id: UUID, *, user_id: UUID) -> None:
        with self._lock:
            self._authorize_task(task_id, user_id, WorkspacePermission.TASK_DELETE)
            del self._items[task_id]

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None
