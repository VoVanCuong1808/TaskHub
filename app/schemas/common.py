"""Shared request and response schemas."""

from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, RootModel

from app.core.constants import (
    DEFAULT_PAGE_LIMIT,
    FULL_NAME_MAX_LENGTH,
    INVALID_NAME_MESSAGE,
    MAX_PAGE_LIMIT,
    MAX_PAGINATION_PAGE,
)


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
    """Validated one-based page pagination shared by collection endpoints."""

    page: int = Field(default=1, ge=1, le=MAX_PAGINATION_PAGE)
    limit: int = Field(default=DEFAULT_PAGE_LIMIT, ge=1, le=MAX_PAGE_LIMIT)

    @property
    def effective_offset(self) -> int:
        return (self.page - 1) * self.limit


class Page[PageItem](BaseModel):
    """Generic paginated response without coupling items to one resource."""

    items: list[PageItem]
    total: int = Field(ge=0)


class ApiErrorDetail(BaseModel):
    """Existing application and authentication error response shape."""

    detail: str


class RequestValidationIssue(BaseModel):
    loc: list[str | int]
    msg: str
    type: str


class RequestValidationDetail(BaseModel):
    """Existing FastAPI request validation response shape."""

    detail: list[RequestValidationIssue]


class ApiErrorOrValidation(RootModel[ApiErrorDetail | RequestValidationDetail]):
    """A route's 422 may be a domain detail or request validation issue list."""
