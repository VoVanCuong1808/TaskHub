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
LABEL_NAME_MAX_LENGTH = 100

INTEGRITY_CONFLICT_MESSAGE = "Resource conflicts with an existing record"
INTEGRITY_RESTRICTED_MESSAGE = "Resource is still referenced and cannot be deleted"
INTEGRITY_REFERENCE_MESSAGE = "Referenced resource does not exist"
