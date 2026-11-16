"""Shared task-management visibility, permission, and lock orchestration."""

from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import (
    CommentNotFoundError,
    InvalidAssigneeError,
    LabelNotFoundError,
    LabelProjectMismatchError,
    ProjectNotFoundError,
    TaskNotFoundError,
)
from app.models.entities import Comment, Label, Project, User, Workspace
from app.models.enums import WorkspacePermission, WorkspaceRole
from app.models.task import Task
from app.services.task_authorization import (
    TaskAssigneeContext,
    TaskAuthorizationContext,
    authorize_task_access,
    validate_task_assignee,
)
from app.services.task_uow import TaskManagementUnitOfWork


@dataclass(frozen=True)
class ProjectGrant:
    project: Project
    workspace: Workspace
    membership_role: WorkspaceRole | None


class TaskAccess:
    """Apply task-domain visibility and lock order through a shared UoW."""

    def __init__(self, uow: TaskManagementUnitOfWork) -> None:
        self._uow = uow

    @staticmethod
    def authorize(
        grant: ProjectGrant, user_id: UUID, permission: WorkspacePermission
    ) -> None:
        authorize_task_access(
            TaskAuthorizationContext(
                project_status=grant.project.status,
                workspace_owner_id=grant.workspace.owner_id,
                membership_role=grant.membership_role,
            ),
            user_id,
            permission,
        )

    async def project(
        self,
        project_id: UUID,
        user_id: UUID,
        permission: WorkspacePermission,
        *,
        write: bool,
        known: ProjectGrant | None = None,
    ) -> ProjectGrant:
        project = known.project if known else await self._uow.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError()
        workspace_id = project.workspace_id
        if write:
            workspace = await self._uow.workspaces.get_for_share(workspace_id)
            if workspace is None:
                raise ProjectNotFoundError()
            member = await self._uow.workspaces.get_member_for_share(
                workspace_id, user_id
            )
            project = await self._uow.projects.get_for_share(project_id)
            if project is None or project.workspace_id != workspace_id:
                raise ProjectNotFoundError()
        else:
            workspace = await self._uow.workspaces.get(workspace_id)
            if workspace is None:
                raise ProjectNotFoundError()
            member = await self._uow.workspaces.get_member(workspace_id, user_id)

        grant = ProjectGrant(project, workspace, member.role if member else None)
        self.authorize(grant, user_id, permission)
        return grant

    async def task(
        self,
        task_id: UUID,
        user_id: UUID,
        permission: WorkspacePermission,
        *,
        write: bool,
    ) -> tuple[Task, ProjectGrant]:
        task = await self._uow.tasks.get(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        try:
            grant = await self.project(
                task.project_id, user_id, permission, write=write
            )
        except ProjectNotFoundError:
            raise TaskNotFoundError(task_id) from None
        if write:
            task = await self._uow.tasks.get_for_update(task_id)
            if task is None or task.project_id != grant.project.id:
                raise TaskNotFoundError(task_id)
        return task, grant

    async def assignee(self, workspace: Workspace, assignee_id: UUID) -> User:
        member = await self._uow.workspaces.get_member_for_share(
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
        return user

    async def label(
        self,
        label_id: UUID,
        user_id: UUID,
        permission: WorkspacePermission,
        *,
        write: bool,
    ) -> tuple[Label, ProjectGrant]:
        label = await self._uow.labels.get(label_id)
        if label is None:
            raise LabelNotFoundError()
        try:
            grant = await self.project(
                label.project_id, user_id, permission, write=write
            )
        except ProjectNotFoundError:
            raise LabelNotFoundError() from None
        if write:
            label = await self._uow.labels.get_for_update(label_id)
            if label is None or label.project_id != grant.project.id:
                raise LabelNotFoundError()
        return label, grant

    async def task_label(
        self, task_id: UUID, label_id: UUID, user_id: UUID
    ) -> tuple[Task, Label]:
        task, read_grant = await self.task(
            task_id, user_id, WorkspacePermission.TASK_READ, write=False
        )
        label = await self._uow.labels.get(label_id)
        if label is None:
            raise LabelNotFoundError()

        if label.project_id == read_grant.project.id:
            self.authorize(read_grant, user_id, WorkspacePermission.LABEL_READ)
        else:
            try:
                await self.project(
                    label.project_id,
                    user_id,
                    WorkspacePermission.LABEL_READ,
                    write=False,
                )
            except ProjectNotFoundError:
                raise LabelNotFoundError() from None

        # Reuse the observed parent project, then reauthorize from locked rows.
        try:
            write_grant = await self.project(
                task.project_id,
                user_id,
                WorkspacePermission.TASK_LABEL_UPDATE,
                write=True,
                known=read_grant,
            )
        except ProjectNotFoundError:
            raise TaskNotFoundError(task_id) from None
        task = await self._uow.tasks.get_for_update(task_id)
        if task is None or task.project_id != write_grant.project.id:
            raise TaskNotFoundError(task_id)
        if label.project_id != task.project_id:
            raise LabelProjectMismatchError()
        label = await self._uow.labels.get_for_update(label_id)
        if label is None:
            raise LabelNotFoundError()
        if label.project_id != write_grant.project.id:
            raise LabelProjectMismatchError()
        return task, label

    async def comment(
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
            grant = await self.project(
                task.project_id, user_id, permission, write=write
            )
        except ProjectNotFoundError:
            raise CommentNotFoundError() from None
        if write:
            task = await self._uow.tasks.get_for_update(parent_task_id)
            if task is None or task.project_id != grant.project.id:
                raise CommentNotFoundError()
            comment = await self._uow.comments.get_for_update(comment_id)
            if comment is None or comment.task_id != parent_task_id:
                raise CommentNotFoundError()
        return comment
