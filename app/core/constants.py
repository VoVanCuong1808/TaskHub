"""Shared constants: error messages and string validation bounds."""

from __future__ import annotations

# Error messages (kept in one place so API and domain stay consistent).
TASK_NOT_FOUND_MESSAGE = "Task {task_id} was not found"
TASK_NOT_FOUND_DESCRIPTION = "Task not found"

# String constraints shared by schemas and OpenAPI docs.
TITLE_MIN_LENGTH = 1
TITLE_MAX_LENGTH = 200
DESCRIPTION_MAX_LENGTH = 2000
