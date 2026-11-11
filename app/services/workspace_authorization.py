"""Pure workspace authorization policy."""

from dataclasses import dataclass
from uuid import UUID

from app.core.authorization import effective_workspace_role, has_workspace_permission
from app.core.exceptions import PermissionDeniedError, WorkspaceNotFoundError
from app.models.enums import WorkspacePermission, WorkspaceRole


@dataclass(frozen=True)
class WorkspaceAuthorizationContext:
    owner_id: UUID
    membership_role: WorkspaceRole | None


def authorize_workspace_access(
    context: WorkspaceAuthorizationContext,
    user_id: UUID,
    permission: WorkspacePermission,
) -> WorkspaceRole:
    """Resolve effective role and raise for hidden or forbidden access."""
    role = effective_workspace_role(
        context.owner_id, user_id, context.membership_role
    )
    if role is None:
        raise WorkspaceNotFoundError()
    if not has_workspace_permission(role, permission):
        raise PermissionDeniedError()
    return role
