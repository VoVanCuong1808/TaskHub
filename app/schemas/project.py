"""Request and response schemas for workspace projects."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
)
from pydantic.json_schema import SkipJsonSchema

from app.core.constants import (
    EXPLICIT_NULL_MESSAGE,
    NAME_MAX_LENGTH,
    PROJECT_DESCRIPTION_MAX_LENGTH,
)
from app.models.enums import ProjectStatus
from app.schemas.common import TrimmedText

ProjectName = Annotated[TrimmedText, Field(min_length=1, max_length=NAME_MAX_LENGTH)]
ProjectDescription = Annotated[
    TrimmedText, Field(max_length=PROJECT_DESCRIPTION_MAX_LENGTH)
]


class ProjectPayloadBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("name", "status", mode="before", check_fields=False)
    @classmethod
    def reject_explicit_null(cls, value: object) -> object:
        if value is None:
            raise ValueError(EXPLICIT_NULL_MESSAGE)
        return value


class ProjectCreate(ProjectPayloadBase):
    name: ProjectName
    description: ProjectDescription | None = None
    status: ProjectStatus = ProjectStatus.ACTIVE


class ProjectUpdate(ProjectPayloadBase):
    name: ProjectName | SkipJsonSchema[None] = Field(default_factory=lambda: None)
    description: ProjectDescription | None = None
    status: ProjectStatus | SkipJsonSchema[None] = Field(default_factory=lambda: None)


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    workspace_id: UUID
    name: str
    description: str | None
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime
