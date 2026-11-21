"""Validated, HTTP-independent representation of a cached task-list page."""

from __future__ import annotations

from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from app.models.enums import TaskPriority, TaskStatus
from app.models.task import Task


class TaskListCacheItem(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True
    )

    id: UUID
    project_id: UUID
    created_by: UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_date: AwareDatetime | None
    assignee_id: UUID | None
    created_at: AwareDatetime
    updated_at: AwareDatetime

    @classmethod
    def from_task(cls, task: Task) -> TaskListCacheItem:
        return cls.model_validate(task, from_attributes=True)

    def to_task(self) -> Task:
        return Task(
            id=self.id,
            project_id=self.project_id,
            created_by=self.created_by,
            title=self.title,
            description=self.description,
            status=self.status,
            priority=self.priority,
            due_date=self.due_date,
            assignee_id=self.assignee_id,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )


class TaskListSnapshot(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, hide_input_in_errors=True
    )

    items: list[TaskListCacheItem]
    total: int = Field(ge=0, strict=True)

    @model_validator(mode="after")
    def total_covers_page(self) -> TaskListSnapshot:
        if self.total < len(self.items):
            raise ValueError("total cannot be less than page item count")
        return self

    @classmethod
    def from_tasks(cls, items: list[Task], total: int) -> TaskListSnapshot:
        return cls(items=[TaskListCacheItem.from_task(task) for task in items], total=total)

    def to_tasks(self) -> tuple[list[Task], int]:
        return [item.to_task() for item in self.items], self.total

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, payload: str | bytes) -> TaskListSnapshot | None:
        try:
            return cls.model_validate_json(payload)
        except (ValidationError, TypeError, ValueError):
            return None
