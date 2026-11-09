"""Task domain model.

Pure Python: no FastAPI / Pydantic imports so the domain stays framework-free.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.models.enums import TaskStatus


def utc_now() -> datetime:
    """Timezone-aware UTC timestamp (never use naive datetimes)."""
    return datetime.now(UTC)


@dataclass(slots=True)
class Task:
    """A task aggregate root."""

    title: str
    description: str | None = None
    status: TaskStatus = TaskStatus.TODO
    id: UUID = field(default_factory=uuid4)
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        """Refresh ``updated_at`` after a mutation."""
        self.updated_at = utc_now()
