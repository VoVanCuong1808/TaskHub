"""Reusable OpenAPI response declarations for existing HTTP error shapes."""

from copy import deepcopy

from app.schemas.common import (
    ApiErrorDetail,
    ApiErrorOrValidation,
    RequestValidationDetail,
)

_ERROR_RESPONSES = {
    401: {
        "model": ApiErrorDetail,
        "description": "Authentication failed.",
        "headers": {
            "WWW-Authenticate": {
                "description": "Bearer authentication challenge.",
                "schema": {"type": "string", "example": "Bearer"},
            }
        },
    },
    403: {
        "model": ApiErrorDetail,
        "description": "The authenticated actor lacks permission.",
    },
    404: {
        "model": ApiErrorDetail,
        "description": "The resource is missing or not visible.",
    },
    409: {
        "model": ApiErrorDetail,
        "description": "The operation conflicts with the current resource state.",
    },
}


def error_responses(
    *status_codes: int, domain_422: bool = False
) -> dict[int, dict[str, object]]:
    """Return fresh FastAPI response declarations for the requested statuses."""
    responses = {code: deepcopy(_ERROR_RESPONSES[code]) for code in status_codes if code != 422}
    if 422 in status_codes:
        responses[422] = {
            "model": ApiErrorOrValidation if domain_422 else RequestValidationDetail,
            "description": (
                "A domain error uses a string detail; request validation uses a "
                "detail issue array."
                if domain_422
                else "Request validation failed; detail contains loc, msg, and type issues."
            ),
        }
    return responses
