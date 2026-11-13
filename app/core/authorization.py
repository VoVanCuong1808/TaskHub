"""Static workspace role permissions."""

from types import MappingProxyType
from typing import Final
from uuid import UUID

from app.models.enums import WorkspacePermission, WorkspaceRole

WORKSPACE_ROLE_PERMISSIONS: Final = MappingProxyType(
    {
        WorkspaceRole.OWNER: frozenset(WorkspacePermission),
        WorkspaceRole.EDITOR: frozenset(
            {
                WorkspacePermission.TASK_READ,
                WorkspacePermission.TASK_CREATE,
                WorkspacePermission.TASK_UPDATE,
                WorkspacePermission.TASK_DELETE,
                WorkspacePermission.WORKSPACE_READ,
                WorkspacePermission.MEMBER_READ,
            }
        ),
        WorkspaceRole.VIEWER: frozenset(
            {
                WorkspacePermission.TASK_READ,
                WorkspacePermission.WORKSPACE_READ,
                WorkspacePermission.MEMBER_READ,
            }
        ),
    }
)
WORKSPACE_WRITE_PERMISSIONS: Final = frozenset(
    {
        WorkspacePermission.TASK_CREATE,
        WorkspacePermission.TASK_UPDATE,
        WorkspacePermission.TASK_DELETE,
        WorkspacePermission.WORKSPACE_UPDATE,
        WorkspacePermission.WORKSPACE_DELETE,
        WorkspacePermission.MEMBER_INVITE,
        WorkspacePermission.MEMBER_UPDATE,
        WorkspacePermission.MEMBER_REMOVE,
    }
)


def has_workspace_permission(
    role: WorkspaceRole, permission: WorkspacePermission
) -> bool:
    """Return whether a workspace role grants the requested permission."""
    return permission in WORKSPACE_ROLE_PERMISSIONS[role]


def effective_workspace_role(
    owner_id: UUID, user_id: UUID, member_role: WorkspaceRole | None
) -> WorkspaceRole | None:
    """Resolve owner authority and demote stale OWNER memberships to viewer."""
    if owner_id == user_id:
        return WorkspaceRole.OWNER
    if member_role is WorkspaceRole.OWNER:
        return WorkspaceRole.VIEWER
    return member_role


def is_workspace_write_permission(permission: WorkspacePermission) -> bool:
    """Return whether a task permission mutates workspace data."""
    return permission in WORKSPACE_WRITE_PERMISSIONS
