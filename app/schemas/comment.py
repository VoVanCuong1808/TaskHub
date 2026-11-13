"""Task-comment request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.constants import INVALID_CONTENT_MESSAGE


class CommentPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1)

    @field_validator("content", mode="before")
    @classmethod
    def reject_nul(cls, value: object) -> object:
        if isinstance(value, str) and "\x00" in value:
            raise ValueError(INVALID_CONTENT_MESSAGE)
        return value


class CommentCreate(CommentPayload):
    pass


class CommentUpdate(CommentPayload):
    pass


class CommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    task_id: UUID
    author_id: UUID
    content: str
    created_at: datetime
    updated_at: datetime
