"""Pure authorization policy for task access through workspace membership."""

from dataclasses import dataclass
from uuid import UUID

from app.core.authorization import (
    has_workspace_permission,
    is_workspace_write_permission,
)
from app.core.exceptions import (
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


def authorize_task_access(
    context: TaskAuthorizationContext,
    user_id: UUID,
    permission: WorkspacePermission,
) -> None:
    """Raise the domain error for invisible, denied, or archived task access."""
    owner = context.workspace_owner_id == user_id
    if owner:
        role = WorkspaceRole.OWNER
    elif context.membership_role is None:
        raise ProjectNotFoundError()
    else:
        role = context.membership_role
    if not has_workspace_permission(role, permission):
        raise PermissionDeniedError()
    if (
        is_workspace_write_permission(permission)
        and context.project_status is ProjectStatus.ARCHIVED
    ):
        raise ProjectArchivedError()
