"""Shared request and response schemas."""

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field

from app.core.constants import FULL_NAME_MAX_LENGTH, INVALID_NAME_MESSAGE


def normalize_full_name(value: object) -> object:
    if isinstance(value, str):
        value = value.strip()
        if "\x00" in value:
            raise ValueError(INVALID_NAME_MESSAGE)
    return value


FullName = Annotated[
    str,
    BeforeValidator(normalize_full_name),
    Field(min_length=1, max_length=FULL_NAME_MAX_LENGTH),
]


class PaginationParams(BaseModel):
    """Validated offset pagination shared by list endpoints."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=100, ge=1, le=200)


class Page[PageItem](BaseModel):
    """Generic paginated response without coupling items to one resource."""

    items: list[PageItem]
    total: int = Field(ge=0)
