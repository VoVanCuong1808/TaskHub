"""Task schemas (Pydantic v2)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from app.core.constants import (
    DESCRIPTION_MAX_LENGTH,
    EXPLICIT_NULL_MESSAGE,
    TITLE_MAX_LENGTH,
    TITLE_MIN_LENGTH,
)
from app.models.enums import TaskPriority, TaskStatus


def normalize_aware_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("due_date must include a timezone")
    return value.astimezone(UTC)


class TaskPayloadBase(BaseModel):
    """Shared config for write payloads: trim strings, reject explicit nulls."""

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator(
        "title", "status", "priority", mode="before", check_fields=False
    )
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        """Required fields accept "absent" but never a JSON ``null``."""
        if value is None:
            raise ValueError(EXPLICIT_NULL_MESSAGE)
        return value

    @field_validator("due_date", check_fields=False)
    @classmethod
    def require_aware_due_date(cls, value: datetime | None) -> datetime | None:
        return normalize_aware_utc(value)


class TaskCreate(TaskPayloadBase):
    project_id: UUID
    title: str = Field(min_length=TITLE_MIN_LENGTH, max_length=TITLE_MAX_LENGTH)
    description: str = Field(default="", max_length=DESCRIPTION_MAX_LENGTH)
    status: TaskStatus = TaskStatus.TODO
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: datetime | None = None
    assignee_id: UUID | None = None


class TaskUpdate(TaskPayloadBase):
    """Partial update: only explicitly sent fields are applied.

    ``description`` follows JSON Merge Patch semantics: an explicit ``null``
    clears the value, while omitting the field leaves it unchanged.
    """

    title: str | SkipJsonSchema[None] = Field(
        default_factory=lambda: None,
        min_length=TITLE_MIN_LENGTH,
        max_length=TITLE_MAX_LENGTH,
    )
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    status: TaskStatus | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    priority: TaskPriority | SkipJsonSchema[None] = Field(
        default_factory=lambda: None
    )
    due_date: datetime | None = None
    assignee_id: UUID | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    title: str
    description: str | None
    status: TaskStatus
    priority: TaskPriority
    due_date: datetime | None
    assignee_id: UUID | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
