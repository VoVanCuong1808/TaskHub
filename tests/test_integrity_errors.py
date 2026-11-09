"""Tests for PostgreSQL integrity-error HTTP status mapping."""

import unittest

from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.main import integrity_error_response


class PostgresError(Exception):
    def __init__(self, sqlstate: str, constraint_name: str | None = None) -> None:
        self.sqlstate = sqlstate
        self.constraint_name = constraint_name


def make_request() -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/v1/tasks",
            "raw_path": b"/api/v1/tasks",
            "query_string": b"",
            "headers": [],
            "server": ("testserver", 80),
            "client": ("testclient", 50000),
            "root_path": "",
        }
    )


class IntegrityErrorResponseTests(unittest.TestCase):
    def response_status(
        self,
        sqlstate: str,
        constraint: str | None = None,
        statement: str = "DELETE FROM tasks",
        nested: bool = False,
    ) -> int:
        original = PostgresError(sqlstate)
        if nested and constraint is not None:
            cause = PostgresError(sqlstate, constraint)
            original.__cause__ = cause
        else:
            original.constraint_name = constraint
        error = IntegrityError(statement, {}, original)
        return integrity_error_response(make_request(), error).status_code

    def test_unique_conflict_maps_to_409(self) -> None:
        self.assertEqual(self.response_status("23505"), 409)

    def test_restricted_delete_maps_to_409(self) -> None:
        self.assertEqual(
            self.response_status("23503", "tasks_created_by_fkey", nested=True), 409
        )

    def test_insert_foreign_key_failure_is_not_delete_restriction(self) -> None:
        self.assertEqual(
            self.response_status(
                "23503", "tasks_created_by_fkey", "INSERT INTO tasks", nested=True
            ),
            422,
        )

    def test_invalid_foreign_key_maps_to_422(self) -> None:
        self.assertEqual(self.response_status("23503", "tasks_project_id_fkey"), 422)

    def test_not_null_maps_to_required_field_422(self) -> None:
        self.assertEqual(self.response_status("23502"), 422)

    def test_check_constraint_maps_to_invalid_input_422(self) -> None:
        self.assertEqual(self.response_status("23514"), 422)
