"""String enums shared by domain and database models."""

from enum import Enum


class TaskStatus(str, Enum):
    """Task lifecycle states."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    DONE = "done"


class UserRole(str, Enum):
    """Account-wide authorization roles."""

    ADMIN = "admin"
    MEMBER = "member"


class WorkspaceRole(str, Enum):
    """Workspace membership permissions."""

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"


class WorkspacePermission(str, Enum):
    """Static permissions for workspace-scoped operations."""

    TASK_READ = "task:read"
    TASK_CREATE = "task:create"
    TASK_UPDATE = "task:update"
    TASK_DELETE = "task:delete"
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_UPDATE = "workspace:update"
    WORKSPACE_DELETE = "workspace:delete"
    MEMBER_READ = "workspace-member:read"
    MEMBER_INVITE = "workspace-member:invite"
    MEMBER_UPDATE = "workspace-member:update"
    MEMBER_REMOVE = "workspace-member:remove"


class ProjectStatus(str, Enum):
    """Project lifecycle states."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class TaskPriority(str, Enum):
    """Task urgency levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"
