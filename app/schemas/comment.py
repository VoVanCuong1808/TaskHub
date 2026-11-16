"""Task-comment request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import TrimmedText


class CommentPayload(BaseModel):
    content: TrimmedText = Field(min_length=1)


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
