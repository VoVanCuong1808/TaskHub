"""HTTP contract tests for project CRUD and archive endpoints."""

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.projects import router as projects_router
from app.core.deps import get_current_user, get_project_service
from app.models.entities import Project, User
from app.models.enums import ProjectStatus, UserRole


class ProjectAPIServiceStub:
    def __init__(self, project: Project) -> None:
        self.project = project
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        self.project.workspace_id = kwargs["workspace_id"]
        self.project.name = kwargs["name"]
        self.project.description = kwargs["description"]
        self.project.status = ProjectStatus.ACTIVE
        return self.project

    async def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return [self.project], 1

    async def get(self, project_id, user_id):
        self.calls.append(("get", {"project_id": project_id, "user_id": user_id}))
        return self.project

    async def update(self, project_id, changes, user_id):
        self.calls.append(("update", {"project_id": project_id, "changes": changes, "user_id": user_id}))
        for name, value in changes.items():
            setattr(self.project, name, value)
        return self.project

    async def delete(self, project_id, user_id):
        self.calls.append(("delete", {"project_id": project_id, "user_id": user_id}))


class ProjectAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self.user = User(
            id=uuid4(),
            email="project-api@example.test",
            full_name="Project API",
            hashed_password="unused",
            role=UserRole.MEMBER,
        )
        now = datetime(2026, 11, 20, tzinfo=UTC)
        self.project = Project(
            id=uuid4(),
            workspace_id=uuid4(),
            name="Initial",
            description="Existing details",
            status=ProjectStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        self.service = ProjectAPIServiceStub(self.project)
        app = FastAPI()
        app.include_router(projects_router, prefix="/api/v1")
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_project_service] = lambda: self.service
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()

    def test_create_and_list_projects_reuse_pagination_contract(self) -> None:
        workspace_id = uuid4()
        created = self.client.post(
            f"/api/v1/workspaces/{workspace_id}/projects",
            json={"name": "  API Project  ", "description": "  Details  "},
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["name"], "API Project")
        self.assertEqual(created.json()["description"], "Details")
        self.assertEqual(created.json()["status"], "active")
        self.assertEqual(created.json()["workspace_id"], str(workspace_id))
        self.assertEqual(self.service.calls[0][1]["user_id"], self.user.id)

        listed = self.client.get(
            f"/api/v1/workspaces/{workspace_id}/projects",
            params={"page": 2, "limit": 3},
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["total"], 1)
        self.assertEqual(self.service.calls[1][1]["offset"], 3)
        self.assertEqual(self.service.calls[1][1]["limit"], 3)
        self.assertEqual(
            self.client.get(
                f"/api/v1/workspaces/{workspace_id}/projects", params={"offset": 0}
            ).status_code,
            422,
        )

    def test_project_payload_validation_and_partial_null_semantics(self) -> None:
        workspace_id = uuid4()
        endpoint = f"/api/v1/workspaces/{workspace_id}/projects"
        for payload in (
            {"name": "   "},
            {"name": "x" * 201},
            {"name": "bad\x00name"},
            {"name": "valid", "description": "x" * 2001},
            {"name": "valid", "description": "bad\x00description"},
            {"name": "valid", "workspace_id": str(uuid4())},
            {"name": "valid", "status": "archived"},
            {"name": "valid", "status": "unknown"},
            {"name": None},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(endpoint, json=payload).status_code, 422)

        boundary = self.client.post(
            endpoint, json={"name": "x" * 200, "description": "y" * 2000}
        )
        self.assertEqual(boundary.status_code, 201, boundary.text)

        project_endpoint = f"/api/v1/projects/{self.project.id}"
        cleared = self.client.patch(project_endpoint, json={"description": None})
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()["description"])
        self.assertEqual(self.service.calls[-1][1]["changes"], {"description": None})
        for payload in (
            {"name": None},
            {"status": None},
            {"status": "unknown"},
            {"workspace_id": str(uuid4())},
            {"unknown": "field"},
        ):
            with self.subTest(payload=payload):
                self.assertEqual(self.client.patch(project_endpoint, json=payload).status_code, 422)

    def test_project_read_update_delete_routes_and_openapi_errors(self) -> None:
        endpoint = f"/api/v1/projects/{self.project.id}"
        self.assertEqual(self.client.get(endpoint).status_code, 200)
        archived = self.client.patch(endpoint, json={"status": "archived"})
        self.assertEqual(archived.status_code, 200, archived.text)
        self.assertEqual(archived.json()["status"], "archived")
        self.assertEqual(archived.json()["name"], "Initial")
        self.assertEqual(archived.json()["description"], "Existing details")
        self.assertEqual(self.client.delete(endpoint).status_code, 204)
        self.assertEqual(self.service.calls[-1][0], "delete")

        schema = self.client.get("/openapi.json").json()
        operations = schema["paths"]
        self.assertEqual(operations["/api/v1/workspaces/{workspace_id}/projects"]["post"]["responses"].keys() & {"201", "401", "403", "404", "422"}, {"201", "401", "403", "404", "422"})
        self.assertEqual(operations["/api/v1/projects/{project_id}"]["delete"]["responses"]["204"]["description"], "Successful Response")
