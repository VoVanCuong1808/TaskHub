"""Workspace and membership API schemas."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
)

from app.core.constants import INVALID_NAME_MESSAGE, NAME_MAX_LENGTH
from app.models.enums import WorkspaceRole


def normalize_workspace_name(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        if "\x00" in value:
            raise ValueError(INVALID_NAME_MESSAGE)
    return value


WorkspaceName = Annotated[
    str,
    BeforeValidator(normalize_workspace_name),
    Field(min_length=1, max_length=NAME_MAX_LENGTH),
]


class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: WorkspaceName


class WorkspaceUpdate(WorkspaceCreate):
    pass


class WorkspaceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    owner_id: UUID
    created_at: datetime
    updated_at: datetime


class WorkspaceMemberWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal[WorkspaceRole.EDITOR, WorkspaceRole.VIEWER]


class WorkspaceMemberCreate(WorkspaceMemberWrite):
    email: EmailStr


class WorkspaceMemberUpdate(WorkspaceMemberWrite):
    pass


class WorkspaceMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    workspace_id: UUID
    user_id: UUID
    role: WorkspaceRole
    created_at: datetime
    updated_at: datetime
