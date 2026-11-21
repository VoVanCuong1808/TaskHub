"""Application event and delivery port for task assignments."""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class TaskAssignmentEvent:
    """Immutable values captured before commit for post-commit notification."""

    task_id: UUID
    task_title: str
    recipient_email: str


class TaskAssignmentNotifier(Protocol):
    async def schedule(self, event: TaskAssignmentEvent) -> None: ...
