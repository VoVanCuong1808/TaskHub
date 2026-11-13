"""Shared page/limit query dependency for collection endpoints."""

from typing import Annotated

from fastapi import Depends, Query, Request
from fastapi.exceptions import RequestValidationError

from app.schemas.common import PaginationParams


def get_pagination(
    pagination: Annotated[PaginationParams, Query()], request: Request
) -> PaginationParams:
    """Parse shared pagination and explicitly reject the removed offset query."""
    if "offset" in request.query_params:
        raise RequestValidationError(
            [
                {
                    "type": "extra_forbidden",
                    "loc": ("query", "offset"),
                    "msg": "The offset query parameter is no longer supported; use page",
                    "input": request.query_params.get("offset"),
                }
            ]
        )
    return pagination


PaginationDep = Annotated[PaginationParams, Depends(get_pagination)]
