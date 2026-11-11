"""Shared constants: error messages and string validation bounds."""

from __future__ import annotations

TASK_NOT_FOUND_DESCRIPTION = "Task not found"
TASK_NOT_FOUND_MESSAGE = TASK_NOT_FOUND_DESCRIPTION
PROJECT_NOT_FOUND_MESSAGE = "Project not found"
INSUFFICIENT_WORKSPACE_ROLE_MESSAGE = "Insufficient workspace role"
PROJECT_ARCHIVED_MESSAGE = "Project is archived"
WORKSPACE_NOT_FOUND_MESSAGE = "Workspace not found"
WORKSPACE_MEMBER_NOT_FOUND_MESSAGE = "Workspace member not found"
WORKSPACE_OWNER_ALREADY_MEMBER_MESSAGE = "Workspace owner is already a member"
WORKSPACE_ALREADY_MEMBER_MESSAGE = "User is already a workspace member"
WORKSPACE_OWNER_ROLE_CHANGE_MESSAGE = "Workspace owner role cannot be changed"
WORKSPACE_OWNER_REMOVE_MESSAGE = "Workspace owner cannot be removed"
WORKSPACE_OWNER_ROLE_RESERVED_MESSAGE = "Workspace OWNER role is reserved for the owner"

EXPLICIT_NULL_MESSAGE = "must not be null; omit the field to leave it unchanged"

TITLE_MIN_LENGTH = 1
TITLE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 2000
EMAIL_MAX_LENGTH = 320
NAME_MAX_LENGTH = 200
FULL_NAME_MAX_LENGTH = 200
LABEL_NAME_MAX_LENGTH = 100
LABEL_COLOR_MAX_LENGTH = 32
PROJECT_DESCRIPTION_MAX_LENGTH = 2000
PASSWORD_HASH_MAX_LENGTH = 255
PASSWORD_MIN_LENGTH = 12
PASSWORD_MAX_LENGTH = 1024
REFRESH_TOKEN_ID_MAX_LENGTH = 36
DEFAULT_LABEL_COLOR = "#777777"
LEGACY_LABEL_WORKSPACE_AMBIGUITY_MESSAGE = (
    "Cannot map legacy label: its workspace must contain exactly one project"
)

INTEGRITY_CONFLICT_MESSAGE = "Resource conflicts with an existing record"
INTEGRITY_RESTRICTED_MESSAGE = "Resource is still referenced and cannot be deleted"
INTEGRITY_REFERENCE_MESSAGE = "Referenced resource does not exist"
INTEGRITY_REQUIRED_MESSAGE = "A required field is missing"
INTEGRITY_INVALID_MESSAGE = "Request violates a data constraint"
AUTH_INVALID_CREDENTIALS_MESSAGE = "Invalid credentials"
AUTH_INVALID_REFRESH_TOKEN_MESSAGE = "Invalid refresh token"
AUTH_NOT_AUTHENTICATED_MESSAGE = "Not authenticated"
AUTH_INACTIVE_ACCOUNT_MESSAGE = "Invalid or inactive account"
AUTH_CURRENT_PASSWORD_INVALID_MESSAGE = "Current password is incorrect"
AUTH_UNTRUSTED_ORIGIN_MESSAGE = "Untrusted Origin"
INVALID_NAME_MESSAGE = "must not contain null characters"
