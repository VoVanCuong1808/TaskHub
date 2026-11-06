"""Domain exceptions.

Raised by services/repositories, translated to HTTP responses in ``app.main``.
"""

from __future__ import annotations

from uuid import UUID

from app.core.constants import TASK_NOT_FOUND_MESSAGE


class TaskNotFoundError(Exception):
    """Raised when a task id does not exist."""

    def __init__(self, task_id: UUID | str) -> None:
        self.task_id = task_id
        super().__init__(TASK_NOT_FOUND_MESSAGE.format(task_id=task_id))
