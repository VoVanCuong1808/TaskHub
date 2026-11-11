"""Static workspace role permissions."""

from types import MappingProxyType
from typing import Final

from app.models.enums import WorkspacePermission, WorkspaceRole

WORKSPACE_ROLE_PERMISSIONS: Final = MappingProxyType(
    {
        WorkspaceRole.OWNER: frozenset(WorkspacePermission),
        WorkspaceRole.EDITOR: frozenset(WorkspacePermission),
        WorkspaceRole.VIEWER: frozenset({WorkspacePermission.TASK_READ}),
    }
)
WORKSPACE_WRITE_PERMISSIONS: Final = frozenset(
    {
        WorkspacePermission.TASK_CREATE,
        WorkspacePermission.TASK_UPDATE,
        WorkspacePermission.TASK_DELETE,
    }
)


def has_workspace_permission(
    role: WorkspaceRole, permission: WorkspacePermission
) -> bool:
    """Return whether a workspace role grants the requested permission."""
    return permission in WORKSPACE_ROLE_PERMISSIONS[role]


def is_workspace_write_permission(permission: WorkspacePermission) -> bool:
    """Return whether a task permission mutates workspace data."""
    return permission in WORKSPACE_WRITE_PERMISSIONS
