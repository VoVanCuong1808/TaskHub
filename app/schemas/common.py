"""Shared validated schema types."""

from typing import Annotated

from pydantic import BeforeValidator, Field

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
