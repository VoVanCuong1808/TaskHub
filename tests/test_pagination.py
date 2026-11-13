"""Tests for shared pagination request and response schemas."""

import unittest
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.router import api_router
from app.api.v1.tasks import router as task_alias_router
from app.core.constants import (
    DEFAULT_PAGE_LIMIT,
    MAX_PAGE_LIMIT,
    MAX_PAGINATION_PAGE,
    MAX_SQL_BIGINT,
)
from app.core.deps import get_current_user, get_task_service, get_workspace_service
from app.schemas.common import Page, PaginationParams


class PaginationSchemaTests(unittest.TestCase):
    def test_defaults_bounds_and_generic_page(self) -> None:
        defaults = PaginationParams()
        self.assertEqual(defaults.page, 1)
        self.assertEqual(defaults.limit, DEFAULT_PAGE_LIMIT)
        self.assertEqual(defaults.effective_offset, 0)
        self.assertEqual(
            Page[str](items=["one"], total=3).model_dump(),
            {"items": ["one"], "total": 3},
        )

        for payload in (
            {"page": 0},
            {"limit": 0},
            {"limit": 201},
            {"page": 9_223_372_036_854_775_807 // 200 + 1},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                PaginationParams.model_validate(payload)

    def test_one_based_page_and_bounded_effective_offset(self) -> None:
        self.assertEqual(PaginationParams(page=1, limit=20).effective_offset, 0)
        self.assertEqual(PaginationParams(page=2, limit=20).effective_offset, 20)
        self.assertLessEqual(
            PaginationParams(
                page=MAX_PAGINATION_PAGE, limit=MAX_PAGE_LIMIT
            ).effective_offset,
            MAX_SQL_BIGINT,
        )


class PaginationApiTests(unittest.TestCase):
    def test_all_list_routes_use_page_limit_and_reject_offset(self) -> None:
        class TaskService:
            async def list(self, **kwargs):
                return [], 0

            async def list_labels(self, **kwargs):
                return [], 0

            async def list_task_labels(self, *args, **kwargs):
                return [], 0

            async def list_comments(self, *args, **kwargs):
                return [], 0

        class WorkspaceService:
            async def list(self, *args, **kwargs):
                return [], 0

            async def list_members(self, *args, **kwargs):
                return [], 0

        app = FastAPI()
        app.include_router(api_router, prefix="/api/v1")
        app.include_router(task_alias_router, include_in_schema=False)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=uuid4())
        app.dependency_overrides[get_task_service] = TaskService
        app.dependency_overrides[get_workspace_service] = WorkspaceService
        project_id, workspace_id, task_id = uuid4(), uuid4(), uuid4()
        paths = (
            ("/api/v1/tasks", {"project_id": str(project_id)}),
            ("/tasks", {"project_id": str(project_id)}),
            ("/api/v1/workspaces", {}),
            (f"/api/v1/workspaces/{workspace_id}/members", {}),
            ("/api/v1/labels", {"project_id": str(project_id)}),
            (f"/api/v1/tasks/{task_id}/labels", {}),
            (f"/api/v1/tasks/{task_id}/comments", {}),
        )

        with TestClient(app) as client:
            for path, extra_params in paths:
                with self.subTest(path=path):
                    defaulted = client.get(path, params=extra_params)
                    self.assertEqual(defaulted.status_code, 200, defaulted.text)
                    paged = client.get(
                        path, params={**extra_params, "page": 2, "limit": 1}
                    )
                    self.assertEqual(paged.status_code, 200, paged.text)
                    obsolete = client.get(
                        path,
                        params={**extra_params, "page": 1, "offset": 0},
                    )
                    self.assertEqual(obsolete.status_code, 422, obsolete.text)
                    self.assertEqual(
                        obsolete.json()["detail"][0]["loc"],
                        ["query", "offset"],
                    )

            openapi = client.get("/openapi.json").json()

        list_paths = (
            "/api/v1/tasks",
            "/api/v1/workspaces",
            "/api/v1/workspaces/{workspace_id}/members",
            "/api/v1/labels",
            "/api/v1/tasks/{task_id}/labels",
            "/api/v1/tasks/{task_id}/comments",
        )
        for path in list_paths:
            with self.subTest(openapi_path=path):
                names = {
                    parameter["name"]
                    for parameter in openapi["paths"][path]["get"]["parameters"]
                }
                self.assertIn("page", names)
                self.assertIn("limit", names)
                self.assertNotIn("offset", names)
                params = {
                    parameter["name"]: parameter
                    for parameter in openapi["paths"][path]["get"]["parameters"]
                }
                self.assertEqual(params["page"]["schema"]["default"], 1)
                self.assertEqual(params["limit"]["schema"]["default"], 20)

        task_update = openapi["components"]["schemas"]["TaskUpdate"]["properties"]
        label_update = openapi["components"]["schemas"]["LabelUpdate"]["properties"]
        for properties, fields in (
            (task_update, ("title", "status", "priority")),
            (label_update, ("name", "color")),
        ):
            for field in fields:
                with self.subTest(schema_field=field):
                    schema = properties[field]
                    self.assertNotIn("default", schema)
                    self.assertNotIn("anyOf", schema)
        for field in ("description", "due_date", "assignee_id"):
            schema = task_update[field]
            self.assertIn("anyOf", schema)
            self.assertTrue(any(item.get("type") == "null" for item in schema["anyOf"]))

    def test_task5_routes_document_runtime_error_shapes_and_statuses(self) -> None:
        app = FastAPI()
        app.include_router(api_router, prefix="/api/v1")
        with TestClient(app) as client:
            openapi = client.get("/openapi.json").json()

        expected = {
            ("/api/v1/tasks", "get"): {401, 404, 422},
            ("/api/v1/tasks", "post"): {401, 403, 404, 409, 422},
            ("/api/v1/tasks/{task_id}", "get"): {401, 404, 422},
            ("/api/v1/tasks/{task_id}", "patch"): {401, 403, 404, 409, 422},
            ("/api/v1/tasks/{task_id}", "delete"): {401, 403, 404, 409, 422},
            ("/api/v1/labels", "get"): {401, 404, 422},
            ("/api/v1/labels", "post"): {401, 403, 404, 409, 422},
            ("/api/v1/labels/{label_id}", "get"): {401, 404, 422},
            ("/api/v1/labels/{label_id}", "patch"): {401, 403, 404, 409, 422},
            ("/api/v1/labels/{label_id}", "delete"): {401, 403, 404, 409, 422},
            ("/api/v1/tasks/{task_id}/labels", "get"): {401, 404, 422},
            (
                "/api/v1/tasks/{task_id}/labels/{label_id}",
                "put",
            ): {401, 403, 404, 409, 422},
            (
                "/api/v1/tasks/{task_id}/labels/{label_id}",
                "delete",
            ): {401, 403, 404, 409, 422},
            ("/api/v1/tasks/{task_id}/comments", "get"): {401, 404, 422},
            ("/api/v1/tasks/{task_id}/comments", "post"): {
                401,
                403,
                404,
                409,
                422,
            },
            ("/api/v1/comments/{comment_id}", "get"): {401, 404, 422},
            ("/api/v1/comments/{comment_id}", "patch"): {
                401,
                403,
                404,
                409,
                422,
            },
            ("/api/v1/comments/{comment_id}", "delete"): {
                401,
                403,
                404,
                409,
                422,
            },
        }
        documented_error_codes = {"401", "403", "404", "409", "422"}
        for (path, method), codes in expected.items():
            operation = openapi["paths"][path][method]
            actual = documented_error_codes.intersection(operation["responses"])
            with self.subTest(path=path, method=method):
                self.assertEqual(actual, {str(code) for code in codes})
                auth_headers = operation["responses"]["401"]["headers"]
                self.assertIn("WWW-Authenticate", auth_headers)
                self.assertEqual(
                    auth_headers["WWW-Authenticate"]["schema"]["example"], "Bearer"
                )
                validation_schema = operation["responses"]["422"]["content"][
                    "application/json"
                ]["schema"]
                schema_ref = validation_schema.get("$ref")
                if "$ref" in validation_schema:
                    ref_name = validation_schema["$ref"].rsplit("/", 1)[-1]
                    validation_schema = openapi["components"]["schemas"][ref_name]
                if method in {"post", "put", "patch", "delete"}:
                    union_key = (
                        "anyOf" if "anyOf" in validation_schema else "oneOf"
                    )
                    variant_refs = {
                        variant.get("$ref", "").rsplit("/", 1)[-1]
                        for variant in validation_schema[union_key]
                    }
                    self.assertIn("ApiErrorDetail", variant_refs)
                    self.assertIn("RequestValidationDetail", variant_refs)
                else:
                    self.assertEqual(
                        schema_ref.rsplit("/", 1)[-1], "RequestValidationDetail"
                    )

