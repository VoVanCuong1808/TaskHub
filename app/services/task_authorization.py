"""Pure authorization policy for task access through workspace membership."""

from dataclasses import dataclass
from uuid import UUID

from app.core.authorization import (
    effective_workspace_role,
    has_workspace_permission,
    is_workspace_write_permission,
)
from app.core.exceptions import (
    CommentAuthorError,
    InvalidAssigneeError,
    PermissionDeniedError,
    ProjectArchivedError,
    ProjectNotFoundError,
)
from app.models.enums import ProjectStatus, WorkspacePermission, WorkspaceRole


@dataclass(frozen=True)
class TaskAuthorizationContext:
    project_status: ProjectStatus
    workspace_owner_id: UUID
    membership_role: WorkspaceRole | None


@dataclass(frozen=True)
class TaskAssigneeContext:
    workspace_owner_id: UUID
    membership_role: WorkspaceRole | None
    is_active: bool


def authorize_task_access(
    context: TaskAuthorizationContext,
    user_id: UUID,
    permission: WorkspacePermission,
) -> None:
    """Raise the domain error for invisible, denied, or archived task access."""
    role = effective_workspace_role(
        context.workspace_owner_id, user_id, context.membership_role
    )
    if role is None:
        raise ProjectNotFoundError()
    if not has_workspace_permission(role, permission):
        raise PermissionDeniedError()
    if (
        is_workspace_write_permission(permission)
        and context.project_status is ProjectStatus.ARCHIVED
    ):
        raise ProjectArchivedError()


def validate_task_assignee(
    context: TaskAssigneeContext, assignee_id: UUID
) -> None:
    """Require an active user with an effective role in the task workspace."""
    if not context.is_active or effective_workspace_role(
        context.workspace_owner_id, assignee_id, context.membership_role
    ) is None:
        raise InvalidAssigneeError()


def authorize_comment_author(author_id: UUID, user_id: UUID) -> None:
    if author_id != user_id:
        raise CommentAuthorError()
