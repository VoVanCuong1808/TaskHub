"""Project-label request and response schemas."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.json_schema import SkipJsonSchema

from app.core.constants import (
    EXPLICIT_NULL_MESSAGE,
    LABEL_COLOR_MAX_LENGTH,
    LABEL_NAME_MAX_LENGTH,
)
from app.schemas.common import TrimmedText


class LabelPayloadBase(BaseModel):
    @field_validator("name", "color", mode="before", check_fields=False)
    @classmethod
    def validate_text(cls, value: object) -> object:
        if value is None:
            raise ValueError(EXPLICIT_NULL_MESSAGE)
        return value


class LabelCreate(LabelPayloadBase):
    project_id: UUID
    name: TrimmedText = Field(min_length=1, max_length=LABEL_NAME_MAX_LENGTH)
    color: TrimmedText = Field(min_length=1, max_length=LABEL_COLOR_MAX_LENGTH)


class LabelUpdate(LabelPayloadBase):
    name: TrimmedText | SkipJsonSchema[None] = Field(
        default_factory=lambda: None,
        min_length=1,
        max_length=LABEL_NAME_MAX_LENGTH,
    )
    color: TrimmedText | SkipJsonSchema[None] = Field(
        default_factory=lambda: None,
        min_length=1,
        max_length=LABEL_COLOR_MAX_LENGTH,
    )


class LabelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    color: str
    created_at: datetime
    updated_at: datetime
