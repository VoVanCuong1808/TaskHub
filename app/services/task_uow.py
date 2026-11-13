"""Application boundary for task-management persistence and transactions."""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.models.entities import (
    Comment,
    Label,
    Project,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.enums import TaskPriority, TaskStatus
from app.models.task import Task


class TaskStore(Protocol):
    async def add(self, task: Task) -> Task: ...

    async def list(
        self,
        *,
        project_id: UUID,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        assignee_id: UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Task], int]: ...

    async def get(self, task_id: UUID) -> Task | None: ...

    async def get_for_update(self, task_id: UUID) -> Task | None: ...

    async def save(self, task: Task) -> Task | None: ...

    async def delete(self, task_id: UUID) -> None: ...


class ProjectStore(Protocol):
    async def get(self, project_id: UUID) -> Project | None: ...

    async def get_for_update(self, project_id: UUID) -> Project | None: ...


class TaskWorkspaceStore(Protocol):
    async def get(self, workspace_id: UUID) -> Workspace | None: ...

    async def get_for_update(self, workspace_id: UUID) -> Workspace | None: ...

    async def get_member(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None: ...

    async def get_member_for_update(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None: ...


class TaskUserStore(Protocol):
    async def get_for_share(self, user_id: UUID) -> User | None: ...


class LabelStore(Protocol):
    async def add(self, label: Label) -> Label: ...

    async def list(
        self, project_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Label], int]: ...

    async def list_for_task(
        self, task_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Label], int]: ...

    async def get(self, label_id: UUID) -> Label | None: ...

    async def get_for_update(self, label_id: UUID) -> Label | None: ...

    async def update(
        self, label: Label, *, name: str | None, color: str | None
    ) -> Label: ...

    async def delete(self, label: Label) -> None: ...

    async def attach(self, task_id: UUID, label_id: UUID) -> None: ...

    async def detach(self, task_id: UUID, label_id: UUID) -> bool: ...


class CommentStore(Protocol):
    async def add(self, comment: Comment) -> Comment: ...

    async def list_for_task(
        self, task_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Comment], int]: ...

    async def get(self, comment_id: UUID) -> Comment | None: ...

    async def get_for_update(self, comment_id: UUID) -> Comment | None: ...

    async def update(self, comment: Comment, content: str) -> Comment: ...

    async def delete(self, comment: Comment) -> None: ...


class TaskManagementUnitOfWork(Protocol):
    tasks: TaskStore
    projects: ProjectStore
    workspaces: TaskWorkspaceStore
    users: TaskUserStore
    labels: LabelStore
    comments: CommentStore

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
