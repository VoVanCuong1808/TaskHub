"""Application port and stable query identity for task-list caching."""

from __future__ import annotations

import hashlib
import json
from typing import Protocol
from uuid import UUID

from app.models.enums import TaskPriority, TaskStatus
from app.models.task import Task


class TaskListCache(Protocol):
    async def generation(self, project_id: UUID) -> str: ...

    async def get(
        self, project_id: UUID, generation: str, query_digest: str
    ) -> tuple[list[Task], int] | None: ...

    async def set_if_current(
        self,
        project_id: UUID,
        generation: str,
        query_digest: str,
        items: list[Task],
        total: int,
    ) -> bool: ...

    async def rotate(self, project_id: UUID) -> None: ...


def task_list_query_digest(
    *,
    q: str | None,
    status: TaskStatus | None,
    priority: TaskPriority | None,
    assignee_id: UUID | None,
    offset: int,
    limit: int,
) -> str:
    dimensions = [
        q,
        status.value if status is not None else None,
        priority.value if priority is not None else None,
        str(assignee_id) if assignee_id is not None else None,
        offset,
        limit,
    ]
    payload = json.dumps(dimensions, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
