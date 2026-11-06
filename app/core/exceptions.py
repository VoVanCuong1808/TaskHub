"""Domain exceptions.

Raised by services/repositories, translated to HTTP responses in ``app.main``.
"""

from __future__ import annotations

from uuid import UUID


class TaskNotFoundError(Exception):
    """Raised when a task id does not exist."""

    def __init__(self, task_id: UUID | str) -> None:
        self.task_id = task_id
        super().__init__(f"Task {task_id} was not found")
