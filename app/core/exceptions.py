"""Domain exceptions.

Raised by services/repositories, translated to HTTP responses in ``app.main``.
"""

from __future__ import annotations

from http import HTTPStatus
from uuid import UUID

from app.core.constants import (
    AUTH_NOT_AUTHENTICATED_MESSAGE,
    INSUFFICIENT_WORKSPACE_ROLE_MESSAGE,
    PROJECT_ARCHIVED_MESSAGE,
    PROJECT_NOT_FOUND_MESSAGE,
    TASK_NOT_FOUND_MESSAGE,
)


class ApplicationError(Exception):
    """Base for application errors translated into HTTP responses."""

    status_code: HTTPStatus

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class AuthenticationError(ApplicationError):
    """Authentication failed or the supplied token is no longer valid."""

    status_code = HTTPStatus.UNAUTHORIZED

    def __init__(self, detail: str = AUTH_NOT_AUTHENTICATED_MESSAGE) -> None:
        super().__init__(detail)


class TaskNotFoundError(ApplicationError):
    """Raised when a task id does not exist."""

    status_code = HTTPStatus.NOT_FOUND

    def __init__(self, task_id: UUID | str) -> None:
        self.task_id = task_id
        super().__init__(TASK_NOT_FOUND_MESSAGE)


class ProjectNotFoundError(ApplicationError):
    """Raised when a project is missing or outside the caller's visibility."""

    status_code = HTTPStatus.NOT_FOUND

    def __init__(self) -> None:
        super().__init__(PROJECT_NOT_FOUND_MESSAGE)


class PermissionDeniedError(ApplicationError):
    """An authenticated workspace member lacks the required workspace role."""

    status_code = HTTPStatus.FORBIDDEN

    def __init__(self) -> None:
        super().__init__(INSUFFICIENT_WORKSPACE_ROLE_MESSAGE)


class ProjectArchivedError(ApplicationError):
    """A task write was attempted in an archived project."""

    status_code = HTTPStatus.CONFLICT

    def __init__(self) -> None:
        super().__init__(PROJECT_ARCHIVED_MESSAGE)
