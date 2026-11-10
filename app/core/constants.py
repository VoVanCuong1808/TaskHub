"""Shared constants: error messages and string validation bounds."""

from __future__ import annotations

TASK_NOT_FOUND_MESSAGE = "Task {task_id} was not found"
TASK_NOT_FOUND_DESCRIPTION = "Task not found"

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
