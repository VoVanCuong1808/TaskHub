"""Domain exceptions.

Raised by services/repositories, translated to HTTP responses in ``app.main``.
"""

from __future__ import annotations

from uuid import UUID


class AuthenticationError(Exception):
    """Authentication failed or the supplied token is no longer valid."""


class TaskNotFoundError(Exception):
    """Raised when a task id does not exist."""

    def __init__(self, task_id: UUID | str) -> None:
        self.task_id = task_id
        super().__init__("Task not found")


class ProjectNotFoundError(Exception):
    """Raised when a project is missing or outside the caller's visibility."""

    def __init__(self) -> None:
        super().__init__("Project not found")


class PermissionDeniedError(Exception):
    """An authenticated workspace member lacks the required workspace role."""

    def __init__(self) -> None:
        super().__init__("Insufficient workspace role")


class ProjectArchivedError(Exception):
    """A task write was attempted in an archived project."""

    def __init__(self) -> None:
        super().__init__("Project is archived")
