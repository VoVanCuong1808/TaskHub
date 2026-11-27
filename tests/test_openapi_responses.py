"""Focused checks for documented error responses on HTTP routes."""

import unittest
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.auth import router as auth_router
from app.api.v1.workspaces import router as workspaces_router
from app.core.deps import get_current_user, get_workspace_service
from app.models.entities import User
from app.models.enums import UserRole


class WorkspaceServiceStub:
    async def list(self, _user_id, *, offset: int, limit: int):
        return [], 0


class OpenAPIResponseTests(unittest.TestCase):
    def test_workspace_errors_are_route_specific_and_logout_has_no_422(self) -> None:
        app = FastAPI()
        app.include_router(auth_router, prefix="/api/v1")
        app.include_router(workspaces_router, prefix="/api/v1")
        paths = app.openapi()["paths"]

        workspace_list = paths["/api/v1/workspaces"]["get"]["responses"]
        self.assertEqual(set(workspace_list) & {"401", "403", "404", "409"}, {"401"})
        self.assertIn("422", workspace_list)

        workspace_create = paths["/api/v1/workspaces"]["post"]["responses"]
        self.assertEqual(set(workspace_create) & {"401", "403", "404", "409"}, {"401"})

        workspace_get = paths["/api/v1/workspaces/{workspace_id}"]["get"]["responses"]
        self.assertTrue({"401", "404"}.issubset(workspace_get))
        self.assertNotIn("403", workspace_get)

        logout = paths["/api/v1/auth/logout"]["post"]["responses"]
        self.assertNotIn("422", logout)
        self.assertIn("401", logout)
        self.assertIn("403", logout)

        user = User(
            id=uuid4(),
            email="openapi@example.test",
            full_name="OpenAPI",
            hashed_password="unused",
            role=UserRole.MEMBER,
        )
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_workspace_service] = WorkspaceServiceStub
        with TestClient(app) as client:
            response = client.get("/api/v1/workspaces")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"items": [], "total": 0})
