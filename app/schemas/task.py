"""Task schemas (Pydantic v2)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import (
    DESCRIPTION_MAX_LENGTH,
    TITLE_MAX_LENGTH,
    TITLE_MIN_LENGTH,
)
from app.models.task import TaskStatus


class TaskPayloadBase(BaseModel):
    """Shared config for write payloads: trim strings, reject explicit nulls."""

    model_config = ConfigDict(str_strip_whitespace=True)

    @field_validator("title", "status", mode="before", check_fields=False)
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        """Required fields accept "absent" but never a JSON ``null``."""
        if value is None:
            raise ValueError("must not be null")
        return value


class TaskCreate(TaskPayloadBase):
    title: str = Field(min_length=TITLE_MIN_LENGTH, max_length=TITLE_MAX_LENGTH)
    description: str = Field(default="", max_length=DESCRIPTION_MAX_LENGTH)
    status: TaskStatus = TaskStatus.TODO


class TaskUpdate(TaskPayloadBase):
    """Partial update: only explicitly sent fields are applied."""

    title: str | None = Field(
        default=None, min_length=TITLE_MIN_LENGTH, max_length=TITLE_MAX_LENGTH
    )
    description: str | None = Field(default=None, max_length=DESCRIPTION_MAX_LENGTH)
    status: TaskStatus | None = None


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    description: str
    status: TaskStatus
    created_at: datetime
    updated_at: datetime
