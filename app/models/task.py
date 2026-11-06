"""Task domain model.

Pure Python: no FastAPI / Pydantic imports so the domain stays framework-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4


class TaskStatus(str, Enum):
    """Allowed lifecycle states for a task."""

    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


def utc_now() -> datetime:
    """Timezone-aware UTC timestamp (never use naive datetimes)."""
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class Task:
    """A task aggregate root."""

    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.TODO
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        """Refresh ``updated_at`` after a mutation."""
        self.updated_at = utc_now()
