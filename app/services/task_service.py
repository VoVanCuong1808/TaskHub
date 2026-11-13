"""Task use cases, authorization orchestration, locking, and transactions."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime
from uuid import UUID

from app.core.constants import DEFAULT_PAGE_LIMIT
from app.core.exceptions import (
    ApplicationError,
    CommentNotFoundError,
    InvalidAssigneeError,
    LabelNotFoundError,
    LabelProjectMismatchError,
    ProjectNotFoundError,
    TaskLabelNotFoundError,
    TaskNotFoundError,
)
from app.models.entities import Comment, Label, Project, Workspace
from app.models.enums import TaskPriority, TaskStatus, WorkspacePermission
from app.models.task import Task
from app.services.task_authorization import (
    TaskAssigneeContext,
    TaskAuthorizationContext,
    authorize_comment_author,
    authorize_task_access,
    validate_task_assignee,
)
from app.services.task_uow import TaskManagementUnitOfWork

logger = logging.getLogger("taskhub")
TASK_UPDATE_FIELDS = frozenset(
    {"title", "description", "status", "priority", "due_date", "assignee_id"}
)
LABEL_UPDATE_FIELDS = frozenset({"name", "color"})


class TaskService:
    def __init__(self, uow: TaskManagementUnitOfWork) -> None:
        self._uow = uow

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        try:
            yield
            await self._uow.commit()
        except ApplicationError:
            await self._uow.rollback()
            raise
        except BaseException:
            logger.exception("Task transaction failed; rolling back")
            await self._uow.rollback()
            raise

    async def _project_access(
        self,
        project_id: UUID,
        user_id: UUID,
        permission: WorkspacePermission,
        *,
        write: bool,
    ) -> tuple[Project, Workspace]:
        project = await self._uow.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError()

        workspace_id = project.workspace_id
        if write:
            workspace = await self._uow.workspaces.get_for_update(workspace_id)
            if workspace is None:
                raise ProjectNotFoundError()
            member = await self._uow.workspaces.get_member_for_update(
                workspace_id, user_id
            )
            project = await self._uow.projects.get_for_update(project_id)
            if project is None or project.workspace_id != workspace_id:
                raise ProjectNotFoundError()
        else:
            workspace = await self._uow.workspaces.get(workspace_id)
            if workspace is None:
                raise ProjectNotFoundError()
            member = await self._uow.workspaces.get_member(workspace_id, user_id)

        authorize_task_access(
            TaskAuthorizationContext(
                project_status=project.status,
                workspace_owner_id=workspace.owner_id,
                membership_role=member.role if member else None,
            ),
            user_id,
            permission,
        )
        return project, workspace

    async def _task_access(
        self,
        task_id: UUID,
        user_id: UUID,
        permission: WorkspacePermission,
        *,
        write: bool,
    ) -> tuple[Task, Project, Workspace]:
        task = await self._uow.tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        try:
            project, workspace = await self._project_access(
                task.project_id, user_id, permission, write=write
            )
        except ProjectNotFoundError:
            raise TaskNotFoundError(task_id) from None
        if write:
            task = await self._uow.tasks.get_for_update(task_id)
            if task is None or task.project_id != project.id:
                raise TaskNotFoundError(task_id)
        return task, project, workspace

    async def _validate_assignee(
        self, workspace: Workspace, assignee_id: UUID
    ) -> None:
        member = await self._uow.workspaces.get_member_for_update(
            workspace.id, assignee_id
        )
        user = await self._uow.users.get_for_share(assignee_id)
        if user is None:
            raise InvalidAssigneeError()
        validate_task_assignee(
            TaskAssigneeContext(
                workspace_owner_id=workspace.owner_id,
                membership_role=member.role if member else None,
                is_active=user.is_active,
            ),
            assignee_id,
        )

    async def _label_access(
        self,
        label_id: UUID,
        user_id: UUID,
        permission: WorkspacePermission,
        *,
        write: bool,
    ) -> tuple[Label, Project, Workspace]:
        label = await self._uow.labels.get(label_id)
        if label is None:
            raise LabelNotFoundError()
        try:
            project, workspace = await self._project_access(
                label.project_id, user_id, permission, write=write
            )
        except ProjectNotFoundError:
            raise LabelNotFoundError() from None
        if write:
            label = await self._uow.labels.get_for_update(label_id)
            if label is None or label.project_id != project.id:
                raise LabelNotFoundError()
        return label, project, workspace

    async def _comment_access(
        self,
        comment_id: UUID,
        user_id: UUID,
        permission: WorkspacePermission,
        *,
        write: bool,
    ) -> Comment:
        comment = await self._uow.comments.get(comment_id)
        if comment is None:
            raise CommentNotFoundError()
        parent_task_id = comment.task_id
        task = await self._uow.tasks.get(parent_task_id)
        if task is None:
            raise CommentNotFoundError()
        try:
            await self._project_access(
                task.project_id, user_id, permission, write=write
            )
        except ProjectNotFoundError:
            raise CommentNotFoundError() from None
        if write:
            task = await self._uow.tasks.get_for_update(parent_task_id)
            if task is None:
                raise CommentNotFoundError()
            comment = await self._uow.comments.get_for_update(comment_id)
            if comment is None or comment.task_id != parent_task_id:
                raise CommentNotFoundError()
        return comment

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
        async with self._transaction():
            _, workspace = await self._project_access(
                project_id, user_id, WorkspacePermission.TASK_CREATE, write=True
            )
            if assignee_id is not None:
                await self._validate_assignee(workspace, assignee_id)
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
        await self._project_access(
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
        task, _, _ = await self._task_access(
            task_id, user_id, WorkspacePermission.TASK_READ, write=False
        )
        return task

    async def update(
        self, task_id: UUID, changes: Mapping[str, object], user_id: UUID
    ) -> Task:
        if changes.keys() - TASK_UPDATE_FIELDS:
            raise ValueError("Unsupported task fields")
        async with self._transaction():
            task, _, workspace = await self._task_access(
                task_id, user_id, WorkspacePermission.TASK_UPDATE, write=True
            )
            assignee_id = changes.get("assignee_id")
            if "assignee_id" in changes and assignee_id is not None:
                await self._validate_assignee(workspace, assignee_id)
            for attribute, value in changes.items():
                setattr(task, attribute, value)
            task.touch()
            saved = await self._uow.tasks.save(task)
            if saved is None:
                raise TaskNotFoundError(task_id)
            return saved

    async def delete(self, task_id: UUID, user_id: UUID) -> None:
        async with self._transaction():
            await self._task_access(
                task_id, user_id, WorkspacePermission.TASK_DELETE, write=True
            )
            await self._uow.tasks.delete(task_id)

    async def create_label(
        self, *, project_id: UUID, user_id: UUID, name: str, color: str
    ) -> Label:
        async with self._transaction():
            await self._project_access(
                project_id, user_id, WorkspacePermission.LABEL_CREATE, write=True
            )
            return await self._uow.labels.add(
                Label(project_id=project_id, name=name, color=color)
            )

    async def list_labels(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[Label], int]:
        await self._project_access(
            project_id, user_id, WorkspacePermission.LABEL_READ, write=False
        )
        return await self._uow.labels.list(
            project_id, offset=offset, limit=limit
        )

    async def get_label(self, label_id: UUID, user_id: UUID) -> Label:
        label, _, _ = await self._label_access(
            label_id, user_id, WorkspacePermission.LABEL_READ, write=False
        )
        return label

    async def update_label(
        self, label_id: UUID, changes: Mapping[str, object], user_id: UUID
    ) -> Label:
        if changes.keys() - LABEL_UPDATE_FIELDS:
            raise ValueError("Unsupported label fields")
        async with self._transaction():
            label, _, _ = await self._label_access(
                label_id, user_id, WorkspacePermission.LABEL_UPDATE, write=True
            )
            return await self._uow.labels.update(
                label,
                name=changes.get("name"),
                color=changes.get("color"),
            )

    async def delete_label(self, label_id: UUID, user_id: UUID) -> None:
        async with self._transaction():
            label, _, _ = await self._label_access(
                label_id, user_id, WorkspacePermission.LABEL_DELETE, write=True
            )
            await self._uow.labels.delete(label)

    async def list_task_labels(
        self,
        task_id: UUID,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[Label], int]:
        await self._task_access(
            task_id, user_id, WorkspacePermission.LABEL_READ, write=False
        )
        return await self._uow.labels.list_for_task(
            task_id, offset=offset, limit=limit
        )

    async def _lock_task_label(
        self, task_id: UUID, label_id: UUID, user_id: UUID
    ) -> Label:
        task, _, _ = await self._task_access(
            task_id, user_id, WorkspacePermission.TASK_READ, write=False
        )
        label = await self._uow.labels.get(label_id)
        if label is None:
            raise LabelNotFoundError()

        try:
            await self._project_access(
                label.project_id,
                user_id,
                WorkspacePermission.LABEL_READ,
                write=False,
            )
        except ProjectNotFoundError:
            raise LabelNotFoundError() from None

        # Resolve write role/archive only after both resources are visible.
        task, project, _ = await self._task_access(
            task_id, user_id, WorkspacePermission.TASK_LABEL_UPDATE, write=True
        )
        if label.project_id != task.project_id:
            raise LabelProjectMismatchError()
        label = await self._uow.labels.get_for_update(label_id)
        if label is None:
            raise LabelNotFoundError()
        if label.project_id != project.id:
            raise LabelProjectMismatchError()
        return label

    async def attach_label(
        self, task_id: UUID, label_id: UUID, user_id: UUID
    ) -> None:
        async with self._transaction():
            await self._lock_task_label(task_id, label_id, user_id)
            await self._uow.labels.attach(task_id, label_id)

    async def detach_label(
        self, task_id: UUID, label_id: UUID, user_id: UUID
    ) -> None:
        async with self._transaction():
            await self._lock_task_label(task_id, label_id, user_id)
            if not await self._uow.labels.detach(task_id, label_id):
                raise TaskLabelNotFoundError()

    async def create_comment(
        self, task_id: UUID, user_id: UUID, content: str
    ) -> Comment:
        async with self._transaction():
            await self._task_access(
                task_id,
                user_id,
                WorkspacePermission.COMMENT_CREATE,
                write=True,
            )
            return await self._uow.comments.add(
                Comment(task_id=task_id, author_id=user_id, content=content)
            )

    async def list_comments(
        self,
        task_id: UUID,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[Comment], int]:
        await self._task_access(
            task_id, user_id, WorkspacePermission.COMMENT_READ, write=False
        )
        return await self._uow.comments.list_for_task(
            task_id, offset=offset, limit=limit
        )

    async def get_comment(self, comment_id: UUID, user_id: UUID) -> Comment:
        return await self._comment_access(
            comment_id, user_id, WorkspacePermission.COMMENT_READ, write=False
        )

    async def update_comment(
        self, comment_id: UUID, user_id: UUID, content: str
    ) -> Comment:
        async with self._transaction():
            comment = await self._comment_access(
                comment_id,
                user_id,
                WorkspacePermission.COMMENT_UPDATE,
                write=True,
            )
            authorize_comment_author(comment.author_id, user_id)
            return await self._uow.comments.update(comment, content)

    async def delete_comment(self, comment_id: UUID, user_id: UUID) -> None:
        async with self._transaction():
            comment = await self._comment_access(
                comment_id,
                user_id,
                WorkspacePermission.COMMENT_DELETE,
                write=True,
            )
            authorize_comment_author(comment.author_id, user_id)
            await self._uow.comments.delete(comment)
