"""HTTP status mappings for application errors."""

import unittest
from http import HTTPStatus

from app.api.v1.auth import authentication_error_response
from app.core.exceptions import (
    AuthenticationError,
    PermissionDeniedError,
    ProjectArchivedError,
    ProjectNotFoundError,
    TaskNotFoundError,
)


class ApplicationErrorTests(unittest.TestCase):
    def test_application_errors_use_standard_http_statuses(self) -> None:
        self.assertEqual(AuthenticationError().status_code, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(TaskNotFoundError("task").status_code, HTTPStatus.NOT_FOUND)
        self.assertEqual(ProjectNotFoundError().status_code, HTTPStatus.NOT_FOUND)
        self.assertEqual(PermissionDeniedError().status_code, HTTPStatus.FORBIDDEN)
        self.assertEqual(ProjectArchivedError().status_code, HTTPStatus.CONFLICT)

    def test_authentication_response_keeps_bearer_challenge(self) -> None:
        response = authentication_error_response(AuthenticationError())
        self.assertEqual(response.status_code, HTTPStatus.UNAUTHORIZED)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
