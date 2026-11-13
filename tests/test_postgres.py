"""PostgreSQL repository and migration integration tests."""

import asyncio
import os
import subprocess
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.core.config import Settings
from app.core.constants import AUTH_INACTIVE_ACCOUNT_MESSAGE
from app.core.exceptions import (
    AuthenticationError,
    ProjectArchivedError,
    TaskNotFoundError,
)
from app.core.security import create_token, decode_token, hash_password_async
from app.db.base import Base
from app.db.legacy_upgrade import upgrade_legacy_schema
from app.db.seed import (
    DEFAULT_PROJECT_ID,
    DEFAULT_USER_ID,
    DEFAULT_WORKSPACE_ID,
    seed_default_data,
)
from app.db.workspace_uow import SQLAlchemyWorkspaceUnitOfWork
from app.main import create_app, integrity_error_response
from app.models.entities import (
    Comment,
    Label,
    Project,
    RefreshSession,
    TaskLabel,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.entities import (
    Task as TaskRow,
)
from app.models.enums import (
    ProjectStatus,
    TaskStatus,
    UserRole,
    WorkspacePermission,
    WorkspaceRole,
)
from app.models.task import Task
from app.repositories.task_database import TaskRepository
from app.repositories.user_repository import UserRepository
from app.schemas.task import TaskUpdate
from app.services.auth_service import AuthService
from app.services.task_service import TaskService
from app.services.workspace_service import WorkspaceService

ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_ENV = "TASKHUB_TEST_DATABASE_URL"


def request_for(method: str) -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
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


async def wait_for_database_lock(session_factory, backend_pid: int) -> None:
    async with session_factory() as session:
        for _ in range(100):
            wait_type = await session.scalar(
                text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"),
                {"pid": backend_pid},
            )
            if wait_type == "Lock":
                return
            await asyncio.sleep(0.01)
    raise AssertionError("database writer did not reach the expected row lock")


async def create_legacy_fixture(
    connection,
    revision: str,
    two_projects: bool = False,
    full_timestamps: bool = False,
    cross_project_label: bool = False,
) -> None:
    statements = [
        "CREATE TYPE user_role AS ENUM ('ADMIN','MEMBER')",
        "CREATE TYPE workspace_role AS ENUM ('OWNER','EDITOR','VIEWER')",
        "CREATE TYPE project_status AS ENUM ('ACTIVE','ARCHIVED')",
        "CREATE TYPE task_status AS ENUM ('TODO','IN_PROGRESS','IN_REVIEW','DONE')",
        "CREATE TYPE task_priority AS ENUM ('LOW','MEDIUM','HIGH','URGENT')",
        "CREATE TABLE users (id UUID PRIMARY KEY, email VARCHAR(320) UNIQUE NOT NULL, name VARCHAR(200) NOT NULL, role user_role NOT NULL, is_active BOOLEAN NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)",
        "CREATE TABLE workspaces (id UUID PRIMARY KEY, name VARCHAR(200) NOT NULL, owner_id UUID NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, CONSTRAINT workspaces_owner_id_fkey FOREIGN KEY(owner_id) REFERENCES users(id))",
        "CREATE TABLE projects (id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, name VARCHAR(200) NOT NULL, status project_status NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)",
        "CREATE TABLE labels (id UUID PRIMARY KEY, workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, name VARCHAR(100) NOT NULL, created_at TIMESTAMPTZ NOT NULL)",
        "CREATE TABLE workspace_members (workspace_id UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE, user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE, role workspace_role NOT NULL, created_at TIMESTAMPTZ NOT NULL, PRIMARY KEY(workspace_id,user_id))",
        "CREATE TABLE tasks (id UUID PRIMARY KEY, project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE, title VARCHAR(200) NOT NULL, description TEXT, status task_status NOT NULL, priority task_priority NOT NULL, due_date TIMESTAMPTZ, assignee_id UUID REFERENCES users(id), created_by_id UUID NOT NULL REFERENCES users(id), created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)",
        "CREATE TABLE comments (id UUID PRIMARY KEY, task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, author_id UUID NOT NULL REFERENCES users(id), body TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)",
        "CREATE TABLE task_labels (task_id UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE, label_id UUID NOT NULL REFERENCES labels(id) ON DELETE CASCADE, PRIMARY KEY(task_id,label_id))",
        "CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)",
        "INSERT INTO users VALUES ('00000000-0000-4000-8000-000000000001','old@example.test','Old User','MEMBER',true,now(),now())",
        "INSERT INTO workspaces VALUES ('00000000-0000-4000-8000-000000000002','Old Workspace','00000000-0000-4000-8000-000000000001',now(),now())",
        "INSERT INTO projects VALUES ('00000000-0000-4000-8000-000000000003','00000000-0000-4000-8000-000000000002','Old Project','ACTIVE',now(),now())",
        "INSERT INTO labels VALUES ('00000000-0000-4000-8000-000000000004','00000000-0000-4000-8000-000000000002','Old Label',now())",
        "INSERT INTO tasks VALUES ('00000000-0000-4000-8000-000000000005','00000000-0000-4000-8000-000000000003','Old Task','description','TODO','LOW',NULL,'00000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000001',now(),now())",
        "INSERT INTO comments VALUES ('00000000-0000-4000-8000-000000000006','00000000-0000-4000-8000-000000000005','00000000-0000-4000-8000-000000000001','old comment',now())",
        "INSERT INTO task_labels VALUES ('00000000-0000-4000-8000-000000000005','00000000-0000-4000-8000-000000000004')",
    ]
    if revision == "9e5ac2ec2ba3":
        audit_statements = [
            "ALTER TABLE tasks ALTER COLUMN description TYPE VARCHAR(2000)",
            "CREATE INDEX ix_comments_author_id ON comments(author_id)",
            "CREATE INDEX ix_comments_task_id ON comments(task_id)",
            "CREATE INDEX ix_labels_workspace_id ON labels(workspace_id)",
            "CREATE INDEX ix_projects_workspace_id ON projects(workspace_id)",
            "CREATE INDEX ix_task_labels_label_id ON task_labels(label_id)",
            "CREATE INDEX ix_tasks_assignee_id ON tasks(assignee_id)",
            "CREATE INDEX ix_tasks_created_by_id ON tasks(created_by_id)",
            "CREATE INDEX ix_tasks_project_id ON tasks(project_id)",
            "CREATE INDEX ix_workspace_members_user_id ON workspace_members(user_id)",
            "CREATE INDEX ix_workspaces_owner_id ON workspaces(owner_id)",
            "ALTER TABLE comments DROP CONSTRAINT comments_author_id_fkey",
            "ALTER TABLE comments ADD CONSTRAINT comments_author_id_fkey FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE RESTRICT",
            "ALTER TABLE tasks DROP CONSTRAINT tasks_assignee_id_fkey",
            "ALTER TABLE tasks ADD CONSTRAINT tasks_assignee_id_fkey FOREIGN KEY(assignee_id) REFERENCES users(id) ON DELETE SET NULL",
            "ALTER TABLE tasks DROP CONSTRAINT tasks_created_by_id_fkey",
            "ALTER TABLE tasks ADD CONSTRAINT tasks_created_by_id_fkey FOREIGN KEY(created_by_id) REFERENCES users(id) ON DELETE RESTRICT",
            "ALTER TABLE workspaces DROP CONSTRAINT workspaces_owner_id_fkey",
            "ALTER TABLE workspaces ADD CONSTRAINT workspaces_owner_id_fkey FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE RESTRICT",
        ]
        first_insert = next(
            index
            for index, statement in enumerate(statements)
            if statement.startswith("INSERT INTO users")
        )
        statements[first_insert:first_insert] = audit_statements
    if full_timestamps:
        replacements = {
            "name VARCHAR(100) NOT NULL, created_at TIMESTAMPTZ NOT NULL)": "name VARCHAR(100) NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)",
            "role workspace_role NOT NULL, created_at TIMESTAMPTZ NOT NULL, PRIMARY KEY": "role workspace_role NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, PRIMARY KEY",
            "body TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL)": "body TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)",
            "label_id UUID NOT NULL REFERENCES labels(id) ON DELETE CASCADE, PRIMARY KEY": "label_id UUID NOT NULL REFERENCES labels(id) ON DELETE CASCADE, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL, PRIMARY KEY",
        }
        statements = [
            next(
                (
                    statement.replace(old, new)
                    for old, new in replacements.items()
                    if old in statement and statement.startswith("CREATE TABLE")
                ),
                statement,
            )
            for statement in statements
        ]
    if two_projects:
        statements.insert(
            statements.index(
                "INSERT INTO labels VALUES ('00000000-0000-4000-8000-000000000004','00000000-0000-4000-8000-000000000002','Old Label',now())"
            ),
            "INSERT INTO projects VALUES ('00000000-0000-4000-8000-000000000007','00000000-0000-4000-8000-000000000002','Second Project','ACTIVE',now(),now())",
        )
    if cross_project_label:
        first_task = next(
            index
            for index, statement in enumerate(statements)
            if statement.startswith("INSERT INTO tasks")
        )
        statements[first_task:first_task] = [
            "INSERT INTO workspaces VALUES ('00000000-0000-4000-8000-000000000008','Other Workspace','00000000-0000-4000-8000-000000000001',now(),now())",
            "INSERT INTO projects VALUES ('00000000-0000-4000-8000-000000000007','00000000-0000-4000-8000-000000000008','Other Project','ACTIVE',now(),now())",
        ]
        statements[first_task + 2] = statements[first_task + 2].replace(
            "00000000-0000-4000-8000-000000000003",
            "00000000-0000-4000-8000-000000000007",
        )
    if full_timestamps:
        for index, statement in enumerate(statements):
            if statement.startswith("INSERT INTO labels"):
                statements[index] = statement[:-1] + ",now())"
            elif statement.startswith("INSERT INTO workspace_members"):
                statements[index] = statement[:-1] + ",now(),now())"
            elif statement.startswith("INSERT INTO comments"):
                statements[index] = statement[:-1] + ",now())"
            elif statement.startswith("INSERT INTO task_labels"):
                statements[index] = statement[:-1] + ",now(),now())"
        statements.append(
            "INSERT INTO workspace_members VALUES ('00000000-0000-4000-8000-000000000002','00000000-0000-4000-8000-000000000001','OWNER',now(),now())"
        )
        for index, statement in enumerate(statements):
            if statement.startswith("INSERT INTO"):
                statements[index] = statement.replace(
                    ",now(),now())",
                    ",TIMESTAMPTZ '2020-01-02 03:04:05+00',"
                    "TIMESTAMPTZ '2021-06-07 08:09:10+00')",
                )
    for statement in statements:
        await connection.execute(text(statement))
    await connection.execute(
        text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": revision}
    )


class PostgreSQLTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        test_url = os.environ.get(TEST_DATABASE_ENV)
        if not test_url:
            raise unittest.SkipTest(f"Set {TEST_DATABASE_ENV} to taskhub_test")
        if make_url(test_url).database != "taskhub_test":
            raise RuntimeError(f"{TEST_DATABASE_ENV} must target taskhub_test")
        cls.test_url = test_url
        cls.migration_env = os.environ.copy()
        cls.migration_env["TASKHUB_DATABASE_URL"] = test_url
        cls.run_migration("downgrade", "base")
        cls.run_migration("upgrade", "head")

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "test_url"):
            cls.run_migration("downgrade", "base")

    @classmethod
    def run_migration(cls, *args: str) -> None:
        subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=ROOT,
            env=cls.migration_env,
            check=True,
        )

    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(self.test_url)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        await seed_default_data(self.session_factory)
        async with self.session_factory() as session:
            await session.execute(delete(TaskRow))
            await session.commit()

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_initial_migration_remains_base_of_auth_migration(self) -> None:
        scripts = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
        revisions = list(scripts.walk_revisions())
        self.assertEqual(len(revisions), 2)
        self.assertEqual(scripts.get_revision("head").down_revision, "552a3882346e")
        self.assertIsNone(scripts.get_revision("552a3882346e").down_revision)

    async def _make_task_auth_fixture(self):
        secret = "day4-test-signing-secret-at-least-32-bytes"
        users = [
            User(
                email=f"{role}-{uuid4().hex}@example.test",
                full_name=role,
                hashed_password="unused",
                role=role_value,
                id=uuid4(),
            )
            for role, role_value in (
                ("owner", UserRole.MEMBER),
                ("editor", UserRole.MEMBER),
                ("viewer", UserRole.MEMBER),
                ("outsider", UserRole.MEMBER),
                ("admin", UserRole.ADMIN),
            )
        ]
        owner, editor, viewer, outsider, admin = users
        workspace = Workspace(name="Task authorization", owner_id=owner.id)
        project = Project(workspace=workspace, name="Visible")
        sibling = Project(workspace=workspace, name="Sibling")
        archived = Project(workspace=workspace, name="Archived", status=ProjectStatus.ARCHIVED)
        other_workspace = Workspace(name="Other", owner_id=outsider.id)
        other_project = Project(workspace=other_workspace, name="Other project")
        async with self.session_factory() as session:
            session.add_all([
                *users, workspace, other_workspace,
                WorkspaceMember(workspace=workspace, user=editor, role=WorkspaceRole.EDITOR),
                WorkspaceMember(workspace=workspace, user=viewer, role=WorkspaceRole.VIEWER),
                project, sibling, archived, other_project,
            ])
            await session.flush()
            existing = TaskRow(project_id=project.id, title="Existing", status=TaskStatus.TODO, created_by=viewer.id, assignee_id=viewer.id)
            other_task = TaskRow(project_id=other_project.id, title="Hidden", status=TaskStatus.TODO, created_by=outsider.id)
            sibling_task = TaskRow(project_id=sibling.id, title="Out of project scope", status=TaskStatus.TODO, created_by=owner.id)
            archived_task = TaskRow(project_id=archived.id, title="Archived read remains allowed", status=TaskStatus.TODO, created_by=owner.id)
            session.add_all([existing, other_task, sibling_task, archived_task])
            await session.commit()
        return SimpleNamespace(
            secret=secret, owner=owner, editor=editor, viewer=viewer,
            outsider=outsider, admin=admin, project=project, sibling=sibling,
            archived=archived, other_project=other_project, existing=existing,
            other_task=other_task, archived_task=archived_task,
        )

    def _task_auth_headers(self, user: User, secret: str) -> dict[str, str]:
        token, _, _ = create_token(secret=secret, subject=user.id, token_type="access", expires_in=timedelta(minutes=10))
        return {"Authorization": f"Bearer {token}"}

    def _task_auth_settings(self) -> Settings:
        return Settings(
            database_url=self.test_url,
            jwt_secret_key=SecretStr("day4-test-signing-secret-at-least-32-bytes"),
            refresh_cookie_secure=False,
        )

    async def test_task_authentication_rejects_missing_invalid_expired_refresh_and_inactive(self) -> None:
        data = await self._make_task_auth_fixture()
        requests = (
            ("/api/v1/tasks", "get", {"params": {"project_id": str(data.project.id)}}),
            ("/api/v1/tasks", "post", {"json": {"project_id": str(data.project.id), "title": "x"}}),
            (f"/api/v1/tasks/{data.existing.id}", "get", {}),
            (f"/api/v1/tasks/{data.existing.id}", "patch", {"json": {"title": "x"}}),
            (f"/api/v1/tasks/{data.existing.id}", "delete", {}),
            ("/tasks", "get", {"params": {"project_id": str(data.project.id)}}),
            ("/tasks", "post", {"json": {"project_id": str(data.project.id), "title": "x"}}),
            (f"/tasks/{data.existing.id}", "get", {}),
            (f"/tasks/{data.existing.id}", "patch", {"json": {"title": "x"}}),
            (f"/tasks/{data.existing.id}", "delete", {}),
        )
        invalid = "invalid"
        expired, _, _ = create_token(secret=data.secret, subject=data.owner.id, token_type="access", expires_in=timedelta(seconds=-1))
        refresh, _, _ = create_token(secret=data.secret, subject=data.owner.id, token_type="refresh", expires_in=timedelta(minutes=10))
        with TestClient(create_app(self._task_auth_settings())) as client:
            for token in ("invalid", invalid, expired, refresh):
                for path, method, kwargs in requests:
                    response = getattr(client, method)(path, headers={"Authorization": f"Bearer {token}"}, **kwargs)
                    self.assertEqual(response.status_code, 401)
                    self.assertEqual(response.headers["www-authenticate"], "Bearer")
            for path, method, kwargs in requests:
                response = getattr(client, method)(path, **kwargs)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")
        async with self.session_factory() as session:
            inactive = await session.get(User, data.outsider.id)
            inactive.is_active = False
            await session.commit()
            await session.refresh(inactive)
            self.assertFalse(inactive.is_active)
        with TestClient(create_app(self._task_auth_settings())) as client:
            for path, method, kwargs in requests:
                response = getattr(client, method)(path, headers=self._task_auth_headers(data.outsider, data.secret), **kwargs)
                self.assertEqual(response.status_code, 401, path)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")

    async def test_owner_editor_crud_and_project_scoped_count_filters_pagination(self) -> None:
        data = await self._make_task_auth_fixture()
        owner_headers = self._task_auth_headers(data.owner, data.secret)
        editor_headers = self._task_auth_headers(data.editor, data.secret)
        project_query = {"project_id": str(data.project.id)}
        with TestClient(create_app(self._task_auth_settings())) as client:
            listing = client.get("/api/v1/tasks", params=project_query, headers=owner_headers)
            self.assertEqual(listing.status_code, 200)
            self.assertEqual([item["id"] for item in listing.json()["items"]], [str(data.existing.id)])
            self.assertEqual(listing.json()["total"], 1)
            self.assertEqual(client.get("/api/v1/tasks", params={**project_query, "offset": 1}, headers=owner_headers).json(), {"items": [], "total": 1})
            self.assertEqual(client.get("/api/v1/tasks", params={**project_query, "status": "done"}, headers=owner_headers).json(), {"items": [], "total": 0})
            self.assertEqual(client.get("/api/v1/tasks", params={"project_id": str(data.sibling.id)}, headers=owner_headers).json()["total"], 1)

            created = client.post("/api/v1/tasks", headers=editor_headers, json={"project_id": str(data.project.id), "title": "Created"})
            self.assertEqual(created.status_code, 201)
            self.assertEqual(created.json()["project_id"], str(data.project.id))
            self.assertEqual(client.get("/api/v1/tasks", params=project_query, headers=editor_headers).status_code, 200)
            self.assertEqual(client.get(f"/api/v1/tasks/{created.json()['id']}", headers=editor_headers).status_code, 200)
            self.assertEqual(client.patch(f"/api/v1/tasks/{created.json()['id']}", headers=editor_headers, json={"description": "updated"}).status_code, 200)
            cleared = client.patch(f"/api/v1/tasks/{created.json()['id']}", headers=editor_headers, json={"description": None})
            self.assertEqual(cleared.status_code, 200)
            self.assertEqual(cleared.json()["title"], "Created")
            self.assertIsNone(cleared.json()["description"])
            editor_deletable = client.post("/api/v1/tasks", headers=editor_headers, json={"project_id": str(data.project.id), "title": "Editor deletes"})
            self.assertEqual(editor_deletable.status_code, 201)
            self.assertEqual(client.delete(f"/api/v1/tasks/{editor_deletable.json()['id']}", headers=editor_headers).status_code, 204)

            owner_created = client.post("/api/v1/tasks", headers=owner_headers, json={"project_id": str(data.project.id), "title": "Owner created"})
            self.assertEqual(owner_created.status_code, 201)
            self.assertEqual(client.delete(f"/api/v1/tasks/{owner_created.json()['id']}", headers=owner_headers).status_code, 204)
            self.assertEqual(client.get(f"/api/v1/tasks/{data.existing.id}", headers=owner_headers).status_code, 200)
            self.assertEqual(client.patch(f"/api/v1/tasks/{data.existing.id}", headers=owner_headers, json={"title": "Owner updated"}).status_code, 200)
            self.assertEqual(client.delete(f"/api/v1/tasks/{data.existing.id}", headers=owner_headers).status_code, 204)
        async with self.session_factory() as session:
            stored = await session.get(TaskRow, UUID(created.json()["id"]))
            self.assertEqual(stored.created_by, data.editor.id)

    async def test_viewer_403_and_archived_409_precedence(self) -> None:
        data = await self._make_task_auth_fixture()
        viewer_headers = self._task_auth_headers(data.viewer, data.secret)
        editor_headers = self._task_auth_headers(data.editor, data.secret)
        owner_headers = self._task_auth_headers(data.owner, data.secret)
        with TestClient(create_app(self._task_auth_settings())) as client:
            self.assertEqual(client.get(f"/api/v1/tasks/{data.existing.id}", headers=viewer_headers).status_code, 200)
            self.assertEqual(client.get("/api/v1/tasks", params={"project_id": str(data.project.id)}, headers=viewer_headers).status_code, 200)
            for response in (
                client.post("/api/v1/tasks", headers=viewer_headers, json={"project_id": str(data.project.id), "title": "Denied"}),
                client.patch(f"/api/v1/tasks/{data.existing.id}", headers=viewer_headers, json={"title": "Denied"}),
                client.delete(f"/api/v1/tasks/{data.existing.id}", headers=viewer_headers),
            ):
                self.assertEqual(response.status_code, 403)
            for response in (
                client.get(f"/api/v1/tasks/{data.archived_task.id}", headers=viewer_headers),
                client.get("/api/v1/tasks", params={"project_id": str(data.archived.id)}, headers=viewer_headers),
            ):
                self.assertEqual(response.status_code, 200)
            for response in (
                client.post("/api/v1/tasks", headers=viewer_headers, json={"project_id": str(data.archived.id), "title": "Denied"}),
                client.patch(f"/api/v1/tasks/{data.archived_task.id}", headers=viewer_headers, json={"title": "Denied"}),
                client.delete(f"/api/v1/tasks/{data.archived_task.id}", headers=viewer_headers),
            ):
                self.assertEqual(response.status_code, 403)

            for headers in (editor_headers, owner_headers):
                created = client.post("/api/v1/tasks", headers=headers, json={"project_id": str(data.archived.id), "title": "No write"})
                self.assertEqual(created.status_code, 409)
                self.assertEqual(created.json(), {"detail": "Project is archived"})
                for response in (
                    client.patch(f"/api/v1/tasks/{data.archived_task.id}", headers=headers, json={"title": "No write"}),
                    client.delete(f"/api/v1/tasks/{data.archived_task.id}", headers=headers),
                ):
                    self.assertEqual(response.status_code, 409)
            archived_list = client.get("/api/v1/tasks", params={"project_id": str(data.archived.id)}, headers=owner_headers)
            self.assertEqual(archived_list.status_code, 200)
            self.assertEqual(archived_list.json()["total"], 1)

    async def test_nonmember_404_hiding_including_global_admin(self) -> None:
        data = await self._make_task_auth_fixture()
        headers_for = lambda user: self._task_auth_headers(user, data.secret)
        with TestClient(create_app(self._task_auth_settings())) as client:
            hidden = client.get(f"/api/v1/tasks/{data.other_task.id}", headers=headers_for(data.admin))
            missing = client.get(f"/api/v1/tasks/{uuid4()}", headers=headers_for(data.admin))
            self.assertEqual(hidden.status_code, 404)
            self.assertEqual(hidden.json(), missing.json())
            for headers in (headers_for(data.editor), headers_for(data.admin)):
                for response in (
                    client.get("/api/v1/tasks", params={"project_id": str(data.other_project.id)}, headers=headers),
                    client.post("/api/v1/tasks", headers=headers, json={"project_id": str(data.other_project.id), "title": "Hidden"}),
                    client.get(f"/api/v1/tasks/{data.other_task.id}", headers=headers),
                    client.patch(f"/api/v1/tasks/{data.other_task.id}", headers=headers, json={"title": "Hidden"}),
                    client.delete(f"/api/v1/tasks/{data.other_task.id}", headers=headers),
                ):
                    self.assertEqual(response.status_code, 404)

    async def test_missing_and_invalid_task_scopes_keep_404_and_422(self) -> None:
        data = await self._make_task_auth_fixture()
        headers = self._task_auth_headers(data.owner, data.secret)
        with TestClient(create_app(self._task_auth_settings())) as client:
            self.assertEqual(client.post("/api/v1/tasks", headers=headers, json={"project_id": str(uuid4()), "title": "Missing"}).status_code, 404)
            self.assertEqual(client.get("/api/v1/tasks", params={"project_id": str(uuid4())}, headers=headers).status_code, 404)
            missing_id = uuid4()
            for response in (
                client.get(f"/api/v1/tasks/{missing_id}", headers=headers),
                client.patch(f"/api/v1/tasks/{missing_id}", headers=headers, json={"title": "Missing"}),
                client.delete(f"/api/v1/tasks/{missing_id}", headers=headers),
            ):
                self.assertEqual(response.status_code, 404)
            self.assertEqual(client.get("/api/v1/tasks", headers=headers).status_code, 422)
            self.assertEqual(client.post("/api/v1/tasks", headers=headers, json={"title": "No project"}).status_code, 422)
            self.assertEqual(client.get("/api/v1/tasks", params={"project_id": "not-a-uuid"}, headers=headers).status_code, 422)

    async def _make_workspace_fixture(self):
        secret = "day4-workspace-test-signing-secret-at-least-32-bytes"
        users = [
            User(
                id=uuid4(),
                email=f"{role}-{uuid4().hex}@example.com",
                full_name=role,
                hashed_password="unused",
                role=global_role,
                is_active=role != "inactive",
            )
            for role, global_role in (
                ("owner", UserRole.MEMBER),
                ("editor", UserRole.MEMBER),
                ("viewer", UserRole.MEMBER),
                ("outsider", UserRole.MEMBER),
                ("admin", UserRole.ADMIN),
                ("invitee", UserRole.MEMBER),
                ("inactive", UserRole.MEMBER),
                ("stale-owner", UserRole.MEMBER),
            )
        ]
        owner, editor, viewer, outsider, admin, invitee, inactive, stale_owner = users
        workspace = Workspace(name="Workspace fixture", owner_id=owner.id)
        other_workspace = Workspace(name="Other workspace", owner_id=outsider.id)
        async with self.session_factory() as session:
            session.add_all([*users, workspace, other_workspace])
            await session.flush()
            session.add_all(
                [
                    WorkspaceMember(
                        workspace_id=workspace.id,
                        user_id=user.id,
                        role=role,
                    )
                    for user, role in (
                        (owner, WorkspaceRole.OWNER),
                        (editor, WorkspaceRole.EDITOR),
                        (viewer, WorkspaceRole.VIEWER),
                    )
                ]
            )
            project = Project(workspace_id=workspace.id, name="Workspace project")
            session.add(project)
            await session.flush()
            task = TaskRow(
                project_id=project.id,
                title="Workspace task",
                status=TaskStatus.TODO,
                created_by=owner.id,
            )
            session.add(task)
            await session.commit()
        return SimpleNamespace(
            secret=secret,
            owner=owner,
            editor=editor,
            viewer=viewer,
            outsider=outsider,
            admin=admin,
            invitee=invitee,
            inactive=inactive,
            stale_owner=stale_owner,
            workspace=workspace,
            other_workspace=other_workspace,
            project=project,
            task=task,
        )

    def _workspace_settings(self, secret: str) -> Settings:
        return Settings(
            database_url=self.test_url,
            jwt_secret_key=SecretStr(secret),
            refresh_cookie_secure=False,
        )

    @staticmethod
    def _workspace_headers(user: User, secret: str) -> dict[str, str]:
        token, _, _ = create_token(
            secret=secret,
            subject=user.id,
            token_type="access",
            expires_in=timedelta(minutes=10),
        )
        return {"Authorization": f"Bearer {token}"}

    async def test_workspace_authentication_and_owner_crud(self) -> None:
        data = await self._make_workspace_fixture()
        headers = self._workspace_headers(data.owner, data.secret)
        with TestClient(create_app(self._workspace_settings(data.secret))) as client:
            missing_id = uuid4()
            unauthenticated = (
                ("get", "/api/v1/workspaces", {}),
                ("post", "/api/v1/workspaces", {"json": {"name": "x"}}),
                ("get", f"/api/v1/workspaces/{missing_id}", {}),
                ("patch", f"/api/v1/workspaces/{missing_id}", {"json": {"name": "x"}}),
                ("delete", f"/api/v1/workspaces/{missing_id}", {}),
                ("get", f"/api/v1/workspaces/{missing_id}/members", {}),
                ("post", f"/api/v1/workspaces/{missing_id}/members", {"json": {"email": "a@example.test", "role": "viewer"}}),
                ("patch", f"/api/v1/workspaces/{missing_id}/members/{uuid4()}", {"json": {"role": "editor"}}),
                ("delete", f"/api/v1/workspaces/{missing_id}/members/{uuid4()}", {}),
            )
            for method, path, kwargs in unauthenticated:
                response = getattr(client, method)(path, **kwargs)
                self.assertEqual(response.status_code, 401, path)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")

            created = client.post(
                "/api/v1/workspaces",
                headers=headers,
                json={"name": "  Created workspace  "},
            )
            self.assertEqual(created.status_code, 201)
            self.assertEqual(created.json()["name"], "Created workspace")
            workspace_id = UUID(created.json()["id"])
            self.assertEqual(created.json()["owner_id"], str(data.owner.id))
            async with self.session_factory() as session:
                membership = await session.get(
                    WorkspaceMember, (workspace_id, data.owner.id)
                )
            self.assertIsNotNone(membership)
            self.assertEqual(membership.role, WorkspaceRole.OWNER)

            listed = client.get("/api/v1/workspaces", headers=headers)
            self.assertIn(workspace_id, [UUID(item["id"]) for item in listed.json()["items"]])
            self.assertEqual(listed.json()["total"], 2)
            workspace_page = client.get(
                "/api/v1/workspaces",
                params={"offset": 1, "limit": 1},
                headers=headers,
            ).json()
            self.assertEqual(len(workspace_page["items"]), 1)
            self.assertEqual(workspace_page["total"], 2)
            self.assertEqual(client.get(f"/api/v1/workspaces/{workspace_id}", headers=headers).status_code, 200)
            renamed = client.patch(
                f"/api/v1/workspaces/{workspace_id}",
                headers=headers,
                json={"name": "Renamed workspace"},
            )
            self.assertEqual(renamed.status_code, 200)
            self.assertEqual(renamed.json()["name"], "Renamed workspace")
            self.assertEqual(client.delete(f"/api/v1/workspaces/{workspace_id}", headers=headers).status_code, 204)
            self.assertEqual(client.get(f"/api/v1/workspaces/{workspace_id}", headers=headers).status_code, 404)

    async def test_workspace_member_lifecycle_and_conflict_409(self) -> None:
        data = await self._make_workspace_fixture()
        headers = self._workspace_headers(data.owner, data.secret)
        member_path = f"/api/v1/workspaces/{data.workspace.id}/members"
        with TestClient(create_app(self._workspace_settings(data.secret))) as client:
            members = client.get(member_path, headers=headers)
            self.assertEqual(members.status_code, 200)
            self.assertEqual(len(members.json()["items"]), 3)
            self.assertEqual(members.json()["total"], 3)
            member_page = client.get(
                member_path,
                params={"offset": 1, "limit": 1},
                headers=headers,
            ).json()
            self.assertEqual(len(member_page["items"]), 1)
            self.assertEqual(member_page["total"], 3)
            invite = client.post(
                member_path,
                headers=headers,
                json={"email": data.invitee.email.upper(), "role": "editor"},
            )
            self.assertEqual(invite.status_code, 201, invite.text)
            self.assertEqual(invite.json()["user_id"], str(data.invitee.id))
            self.assertEqual(invite.json()["role"], "editor")
            self.assertEqual(
                client.post(member_path, headers=headers, json={"email": data.invitee.email, "role": "viewer"}).status_code,
                409,
            )
            self.assertEqual(
                client.post(member_path, headers=headers, json={"email": data.owner.email, "role": "viewer"}).status_code,
                409,
            )
            self.assertEqual(
                client.post(member_path, headers=headers, json={"email": "missing@example.com", "role": "viewer"}).status_code,
                404,
            )
            self.assertEqual(
                client.post(member_path, headers=headers, json={"email": data.inactive.email, "role": "viewer"}).status_code,
                404,
            )
            for email in ("missing@example.com", data.inactive.email):
                self.assertEqual(
                    client.post(
                        member_path,
                        headers=headers,
                        json={"email": email, "role": "owner"},
                    ).status_code,
                    422,
                )
            self.assertEqual(
                client.post(
                    member_path,
                    headers=headers,
                    json={"email": data.outsider.email, "role": "owner"},
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(member_path, headers=headers, json={"email": data.invitee.email, "role": "owner"}).status_code,
                422,
            )
            self.assertEqual(
                client.patch(f"{member_path}/{data.owner.id}", headers=headers, json={"role": "editor"}).status_code,
                409,
            )
            self.assertEqual(
                client.patch(f"{member_path}/{data.viewer.id}", headers=headers, json={"role": "owner"}).status_code,
                422,
            )
            self.assertEqual(client.delete(f"{member_path}/{data.owner.id}", headers=headers).status_code, 409)

            changed = client.patch(
                f"{member_path}/{data.viewer.id}",
                headers=headers,
                json={"role": "editor"},
            )
            self.assertEqual(changed.status_code, 200)
            self.assertEqual(changed.json()["role"], "editor")
            self.assertEqual(client.delete(f"{member_path}/{data.viewer.id}", headers=headers).status_code, 204)
            self.assertEqual(client.delete(f"{member_path}/{data.viewer.id}", headers=headers).status_code, 404)
            missing_id = uuid4()
            self.assertEqual(
                client.patch(f"{member_path}/{missing_id}", headers=headers, json={"role": "editor"}).status_code,
                404,
            )
            self.assertEqual(
                client.patch(f"{member_path}/{missing_id}", headers=headers, json={"role": "owner"}).status_code,
                422,
            )

    async def test_workspace_member_role_403_and_cross_workspace_404(self) -> None:
        data = await self._make_workspace_fixture()
        with TestClient(create_app(self._workspace_settings(data.secret))) as client:
            for user in (data.editor, data.viewer):
                headers = self._workspace_headers(user, data.secret)
                self.assertEqual(client.get(f"/api/v1/workspaces/{data.workspace.id}", headers=headers).status_code, 200)
                self.assertEqual(client.get(f"/api/v1/workspaces/{data.workspace.id}/members", headers=headers).status_code, 200)
                operations = (
                    ("patch", f"/api/v1/workspaces/{data.workspace.id}", {"json": {"name": "Denied"}}),
                    ("delete", f"/api/v1/workspaces/{data.workspace.id}", {}),
                    ("post", f"/api/v1/workspaces/{data.workspace.id}/members", {"json": {"email": data.invitee.email, "role": "viewer"}}),
                    ("patch", f"/api/v1/workspaces/{data.workspace.id}/members/{data.viewer.id}", {"json": {"role": "editor"}}),
                    ("delete", f"/api/v1/workspaces/{data.workspace.id}/members/{data.viewer.id}", {}),
                )
                for method, path, kwargs in operations:
                    response = getattr(client, method)(path, headers=headers, **kwargs)
                    self.assertEqual(response.status_code, 403, f"{method} {path} as {user.email}")
                self.assertEqual(
                    client.patch(
                        f"/api/v1/workspaces/{data.workspace.id}/members/{uuid4()}",
                        headers=headers,
                        json={"role": "owner"},
                    ).status_code,
                    422,
                )

            for user in (data.outsider, data.admin):
                headers = self._workspace_headers(user, data.secret)
                visible = client.get("/api/v1/workspaces", headers=headers).json()["items"]
                self.assertNotIn(str(data.workspace.id), [item["id"] for item in visible])
                self.assertEqual(client.get(f"/api/v1/workspaces/{data.workspace.id}", headers=headers).status_code, 404)
                self.assertEqual(client.get(f"/api/v1/workspaces/{data.workspace.id}/members", headers=headers).status_code, 404)
                for method, path, kwargs in (
                    ("patch", f"/api/v1/workspaces/{data.workspace.id}", {"json": {"name": "Hidden"}}),
                    ("delete", f"/api/v1/workspaces/{data.workspace.id}", {}),
                    ("post", f"/api/v1/workspaces/{data.workspace.id}/members", {"json": {"email": data.invitee.email, "role": "viewer"}}),
                    ("patch", f"/api/v1/workspaces/{data.workspace.id}/members/{data.viewer.id}", {"json": {"role": "editor"}}),
                    ("delete", f"/api/v1/workspaces/{data.workspace.id}/members/{data.viewer.id}", {}),
                ):
                    self.assertEqual(getattr(client, method)(path, headers=headers, **kwargs).status_code, 404)
                self.assertEqual(
                    client.patch(
                        f"/api/v1/workspaces/{data.workspace.id}/members/{uuid4()}",
                        headers=headers,
                        json={"role": "owner"},
                    ).status_code,
                    422,
                )
            owner_headers = self._workspace_headers(data.owner, data.secret)
            missing_id = uuid4()
            for method, path, kwargs in (
                ("get", f"/api/v1/workspaces/{missing_id}", {}),
                ("patch", f"/api/v1/workspaces/{missing_id}", {"json": {"name": "Missing"}}),
                ("delete", f"/api/v1/workspaces/{missing_id}", {}),
                ("get", f"/api/v1/workspaces/{missing_id}/members", {}),
            ):
                self.assertEqual(getattr(client, method)(path, headers=owner_headers, **kwargs).status_code, 404)

    async def test_stale_owner_is_viewer_but_owner_id_keeps_authority(self) -> None:
        data = await self._make_workspace_fixture()
        async with self.session_factory() as session:
            await session.delete(
                await session.get(WorkspaceMember, (data.workspace.id, data.owner.id))
            )
            session.add(
                WorkspaceMember(
                    workspace_id=data.workspace.id,
                    user_id=data.stale_owner.id,
                    role=WorkspaceRole.OWNER,
                )
            )
            await session.commit()
        stale_headers = self._workspace_headers(data.stale_owner, data.secret)
        owner_headers = self._workspace_headers(data.owner, data.secret)
        member_path = f"/api/v1/workspaces/{data.workspace.id}/members"
        with TestClient(create_app(self._workspace_settings(data.secret))) as client:
            self.assertEqual(
                client.patch(
                    f"{member_path}/{data.owner.id}",
                    headers=owner_headers,
                    json={"role": "editor"},
                ).status_code,
                404,
            )
            self.assertEqual(
                client.delete(
                    f"{member_path}/{data.owner.id}", headers=owner_headers
                ).status_code,
                404,
            )
            self.assertEqual(client.get(f"/api/v1/workspaces/{data.workspace.id}", headers=stale_headers).status_code, 200)
            self.assertEqual(client.get(member_path, headers=stale_headers).status_code, 200)
            for method, path, kwargs in (
                ("patch", f"/api/v1/workspaces/{data.workspace.id}", {"json": {"name": "Stale"}}),
                ("post", member_path, {"json": {"email": data.invitee.email, "role": "viewer"}}),
                ("patch", f"{member_path}/{data.viewer.id}", {"json": {"role": "editor"}}),
                ("delete", f"{member_path}/{data.viewer.id}", {}),
            ):
                self.assertEqual(getattr(client, method)(path, headers=stale_headers, **kwargs).status_code, 403)
            self.assertEqual(client.get(f"/api/v1/tasks/{data.task.id}", headers=stale_headers).status_code, 200)
            for response in (
                client.post("/api/v1/tasks", headers=stale_headers, json={"project_id": str(data.project.id), "title": "Denied"}),
                client.patch(f"/api/v1/tasks/{data.task.id}", headers=stale_headers, json={"title": "Denied"}),
                client.delete(f"/api/v1/tasks/{data.task.id}", headers=stale_headers),
            ):
                self.assertEqual(response.status_code, 403)
            self.assertEqual(client.patch(f"/api/v1/workspaces/{data.workspace.id}", headers=owner_headers, json={"name": "Owner authority"}).status_code, 200)
            invited = client.post(
                member_path,
                headers=owner_headers,
                json={"email": data.invitee.email, "role": "viewer"},
            )
            self.assertEqual(invited.status_code, 201)
            changed_member = client.patch(
                f"{member_path}/{data.editor.id}",
                headers=owner_headers,
                json={"role": "viewer"},
            )
            self.assertEqual(changed_member.status_code, 200)
            self.assertEqual(
                client.delete(f"{member_path}/{data.viewer.id}", headers=owner_headers).status_code,
                204,
            )
            created_task = client.post("/api/v1/tasks", headers=owner_headers, json={"project_id": str(data.project.id), "title": "Owner authority"})
            self.assertEqual(created_task.status_code, 201)
            task_id = created_task.json()["id"]
            self.assertEqual(client.patch(f"/api/v1/tasks/{task_id}", headers=owner_headers, json={"title": "Owner update"}).status_code, 200)
            self.assertEqual(client.delete(f"/api/v1/tasks/{task_id}", headers=owner_headers).status_code, 204)

    async def test_workspace_update_failure_rolls_back(self) -> None:
        data = await self._make_workspace_fixture()
        with self.assertRaises(DBAPIError):
            async with self.session_factory() as session:
                await WorkspaceService(SQLAlchemyWorkspaceUnitOfWork(session)).update(
                    data.workspace.id, data.owner.id, "x" * 201
                )
        async with self.session_factory() as session:
            stored = await session.get(Workspace, data.workspace.id)
        self.assertEqual(stored.name, "Workspace fixture")

    async def test_workspace_role_revocation_serializes_with_task_write(self) -> None:
        data = await self._make_workspace_fixture()
        task_authorized = asyncio.Event()
        release_task = asyncio.Event()
        remover_pid_ready = asyncio.Event()
        remover_pid: int | None = None

        async def hold_task_write() -> None:
            async with self.session_factory() as session:
                task = await TaskRepository(session)._authorize_task(
                    data.task.id, data.editor.id, WorkspacePermission.TASK_UPDATE
                )
                task_authorized.set()
                await release_task.wait()
                task.title = "write completed before revocation"
                await session.commit()

        async def revoke_editor() -> None:
            nonlocal remover_pid
            async with self.session_factory() as session:
                remover_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                remover_pid_ready.set()
                await WorkspaceService(SQLAlchemyWorkspaceUnitOfWork(session)).remove_member(
                    data.workspace.id, data.owner.id, data.editor.id
                )

        writer = asyncio.create_task(hold_task_write())
        await task_authorized.wait()
        revoker = asyncio.create_task(revoke_editor())
        await remover_pid_ready.wait()
        self.assertIsNotNone(remover_pid)
        await wait_for_database_lock(self.session_factory, remover_pid)
        release_task.set()
        await asyncio.wait_for(writer, timeout=5)
        await asyncio.wait_for(revoker, timeout=5)
        async with self.session_factory() as session:
            stored_task = await session.get(TaskRow, data.task.id)
            membership = await session.get(
                WorkspaceMember, (data.workspace.id, data.editor.id)
            )
        self.assertEqual(stored_task.title, "write completed before revocation")
        self.assertIsNone(membership)
    async def test_auth_profile_password_rotation_and_persistence(self) -> None:
        settings = Settings(
            database_url=self.test_url,
            jwt_secret_key=SecretStr("day3-test-signing-secret-at-least-32-bytes"),
            refresh_cookie_secure=False,
        )
        app = create_app(settings)
        email = f"{uuid4().hex}@example.com"
        password = "  this password keeps surrounding spaces  "
        with TestClient(app, headers={"Origin": "http://testserver"}) as client:
            invalid_register = client.post(
                "/api/v1/auth/register",
                json={
                    "email": email,
                    "full_name": "User",
                    "password": "qZ9!",
                    "role": "admin",
                },
            )
            self.assertEqual(invalid_register.status_code, 422)
            self.assertNotIn("qZ9!", invalid_register.text)
            self.assertNotIn("admin", invalid_register.text)

            registered = client.post(
                "/api/v1/auth/register",
                json={
                    "email": email.upper(),
                    "full_name": "  Auth User  ",
                    "password": password,
                },
            )
            self.assertEqual(registered.status_code, 201)
            self.assertEqual(registered.json()["email"], email)
            self.assertEqual(registered.json()["full_name"], "Auth User")
            self.assertEqual(registered.json()["role"], "member")
            self.assertNotIn("hashed_password", registered.json())
            self.assertEqual(
                client.post(
                    "/api/v1/auth/register",
                    json={
                        "email": email,
                        "full_name": "Duplicate",
                        "password": password,
                    },
                ).status_code,
                409,
            )

            self.assertEqual(client.get("/api/v1/users/me").status_code, 401)
            self.assertEqual(
                client.post(
                    "/api/v1/auth/login",
                    json={"email": email, "password": "wrong password"},
                ).json()["detail"],
                "Invalid credentials",
            )
            self.assertEqual(
                client.post(
                    "/api/v1/auth/login",
                    json={"email": "nobody@example.com", "password": "wrong password"},
                ).json()["detail"],
                "Invalid credentials",
            )
            for origin in ("", "null", "https://attacker.example"):
                rejected = client.post(
                    "/api/v1/auth/login",
                    headers={"Origin": origin},
                    json={"email": email, "password": password},
                )
                self.assertEqual(rejected.status_code, 403)
                self.assertNotIn("set-cookie", rejected.headers)

            client.headers.pop("Origin")
            logged_in = client.post(
                "/api/v1/auth/login", json={"email": email, "password": password}
            )
            client.headers["Origin"] = "http://testserver"
            self.assertEqual(logged_in.status_code, 200)
            pair = logged_in.json()
            access = pair["access_token"]
            self.assertNotIn("refresh_token", pair)
            cookie = client.cookies.get("refresh_token")
            self.assertTrue(cookie)
            set_cookie = logged_in.headers["set-cookie"].lower()
            self.assertIn("httponly", set_cookie)
            self.assertIn("samesite=lax", set_cookie)
            self.assertIn("path=/api/v1/auth", set_cookie)
            self.assertIn("max-age=2592000", set_cookie)
            self.assertIn(
                "secure", set_cookie
            ) if settings.refresh_cookie_secure else self.assertNotIn(
                "secure", set_cookie
            )
            self.assertIn("no-store", logged_in.headers["cache-control"])
            blocked_refresh = client.post(
                "/api/v1/auth/refresh", headers={"Origin": "https://attacker.example"}
            )
            self.assertEqual(blocked_refresh.status_code, 403)
            self.assertNotIn("set-cookie", blocked_refresh.headers)
            self.assertEqual(client.cookies.get("refresh_token"), cookie)
            headers = {"Authorization": f"Bearer {access}"}
            self.assertEqual(
                client.get("/api/v1/users/me", headers=headers).status_code, 200
            )
            self.assertEqual(
                client.get(
                    "/api/v1/users/me", headers={"Authorization": "Bearer invalid"}
                ).status_code,
                401,
            )
            client.cookies.clear()
            expired_cookie, _, _ = create_token(
                secret=settings.jwt_secret_key.get_secret_value(),
                subject=uuid4(),
                token_type="refresh",
                expires_in=timedelta(seconds=-1),
            )
            for bad_cookie in (access, expired_cookie):
                rejected_cookie = client.post(
                    "/api/v1/auth/refresh",
                    headers={"Cookie": f"refresh_token={bad_cookie}"},
                )
                self.assertEqual(rejected_cookie.status_code, 401)
                self.assertNotIn("set-cookie", rejected_cookie.headers)
            body_fallback = client.post(
                "/api/v1/auth/refresh", json={"refresh_token": cookie}
            )
            self.assertEqual(body_fallback.status_code, 401)
            client.cookies.set(
                "refresh_token", cookie, domain="testserver.local", path="/api/v1/auth"
            )
            schema = client.get("/openapi.json").json()
            self.assertIn("HTTPBearer", schema["components"]["securitySchemes"])
            self.assertEqual(
                set(schema["components"]["schemas"]["AccessToken"]["properties"]),
                {"access_token", "token_type"},
            )

            async with self.session_factory() as session:
                service = AuthService(
                    UserRepository(session),
                    secret=settings.jwt_secret_key.get_secret_value(),
                    access_minutes=settings.access_token_minutes,
                    refresh_days=settings.refresh_token_days,
                )
                race_email = f"race-{uuid4().hex}@example.com"
                await service.register(race_email, "Race User", password)
                race_token = (await service.login(race_email, password))[
                    "refresh_token"
                ]

            async def refresh_once():
                async with self.session_factory() as session:
                    service = AuthService(
                        UserRepository(session),
                        secret=settings.jwt_secret_key.get_secret_value(),
                        access_minutes=settings.access_token_minutes,
                        refresh_days=settings.refresh_token_days,
                    )
                    try:
                        return await service.refresh(race_token)
                    except AuthenticationError:
                        return None

            race_results = await asyncio.gather(refresh_once(), refresh_once())
            self.assertEqual(sum(result is not None for result in race_results), 1)

            rotated = client.post("/api/v1/auth/refresh")
            self.assertEqual(rotated.status_code, 200)
            rotated_cookie = client.cookies.get("refresh_token")
            self.assertNotEqual(rotated_cookie, cookie)
            self.assertNotIn("refresh_token", rotated.json())
            client.cookies.set(
                "refresh_token",
                rotated_cookie,
                domain="testserver.local",
                path="/api/v1/auth",
            )
            logged_out = client.post("/api/v1/auth/logout")
            self.assertEqual(logged_out.status_code, 204)
            self.assertIn("max-age=0", logged_out.headers["set-cookie"].lower())
            self.assertEqual(
                client.post("/api/v1/auth/refresh").status_code,
                401,
            )
            invalid_logout = client.post("/api/v1/auth/logout")
            self.assertEqual(invalid_logout.status_code, 401)
            self.assertEqual(invalid_logout.headers["www-authenticate"], "Bearer")
            self.assertIn("max-age=0", invalid_logout.headers["set-cookie"].lower())
            self.assertEqual(invalid_logout.headers["cache-control"], "no-store")
            self.assertEqual(invalid_logout.headers["pragma"], "no-cache")

            replay = client.post(
                "/api/v1/auth/refresh", headers={"Cookie": f"refresh_token={cookie}"}
            )
            self.assertEqual(replay.status_code, 401)
            self.assertNotIn("set-cookie", replay.headers)

            persistent_login_response = client.post(
                "/api/v1/auth/login", json={"email": email, "password": password}
            )
            persistent_login = persistent_login_response.json()
            persistent_cookie = client.cookies.get("refresh_token")

        with TestClient(
            create_app(settings), headers={"Origin": "http://testserver"}
        ) as client:
            client.cookies.set(
                "refresh_token",
                persistent_cookie,
                domain="testserver.local",
                path="/api/v1/auth",
            )
            after_restart = client.post("/api/v1/auth/refresh")
            self.assertEqual(after_restart.status_code, 200)

            access = persistent_login["access_token"]
            headers = {"Authorization": f"Bearer {access}"}

            forbidden = client.patch(
                "/api/v1/users/me",
                headers=headers,
                json={"role": "admin", "is_active": False},
            )
            self.assertEqual(forbidden.status_code, 422)
            self.assertNotIn("admin", forbidden.text)
            self.assertEqual(
                client.patch(
                    "/api/v1/users/me", headers=headers, json={"full_name": None}
                ).status_code,
                422,
            )
            updated = client.patch(
                "/api/v1/users/me",
                headers=headers,
                json={"full_name": "Updated User", "email": f"updated-{email}"},
            )
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(updated.json()["full_name"], "Updated User")

            self.assertEqual(
                client.post(
                    "/api/v1/users/me/change-password",
                    headers=headers,
                    json={
                        "current_password": "wrong",
                        "new_password": "new secure password",
                    },
                ).status_code,
                401,
            )
            self.assertEqual(
                client.post(
                    "/api/v1/users/me/change-password",
                    headers=headers,
                    json={
                        "current_password": password,
                        "new_password": "new secure password",
                    },
                ).status_code,
                204,
            )
            self.assertEqual(
                client.post(
                    "/api/v1/auth/refresh",
                ).status_code,
                401,
            )
            self.assertEqual(
                client.post(
                    "/api/v1/auth/login",
                    json={"email": f"updated-{email}", "password": password},
                ).status_code,
                401,
            )
            new_login = client.post(
                "/api/v1/auth/login",
                json={"email": f"updated-{email}", "password": "new secure password"},
            )
            self.assertEqual(new_login.status_code, 200)

        async with self.session_factory() as session:
            inactive = await session.scalar(
                select(User).where(User.email == f"updated-{email}")
            )
            inactive.is_active = False
            await session.commit()
        with TestClient(
            create_app(settings), headers={"Origin": "http://testserver"}
        ) as client:
            inactive_headers = {
                "Authorization": f"Bearer {new_login.json()['access_token']}"
            }
            self.assertEqual(
                client.get("/api/v1/users/me", headers=inactive_headers).status_code,
                401,
            )
            self.assertEqual(
                client.post(
                    "/api/v1/auth/login",
                    json={
                        "email": f"updated-{email}",
                        "password": "new secure password",
                    },
                ).status_code,
                401,
            )

    async def test_refresh_replay_commits_user_session_revocation(self) -> None:
        settings = Settings(
            database_url=self.test_url,
            jwt_secret_key=SecretStr("day3-test-signing-secret-at-least-32-bytes"),
            refresh_cookie_secure=False,
        )
        email = f"{uuid4().hex}@example.com"
        async with self.session_factory() as session:
            service = AuthService(
                UserRepository(session),
                secret=settings.jwt_secret_key.get_secret_value(),
                access_minutes=settings.access_token_minutes,
                refresh_days=settings.refresh_token_days,
            )
            user = await service.register(
                email, "Replay User", "long password for test"
            )
        async with self.session_factory() as session:
            service = AuthService(
                UserRepository(session),
                secret=settings.jwt_secret_key.get_secret_value(),
                access_minutes=settings.access_token_minutes,
                refresh_days=settings.refresh_token_days,
            )
            first = await service.login(email, "long password for test")
        async with self.session_factory() as session:
            service = AuthService(
                UserRepository(session),
                secret=settings.jwt_secret_key.get_secret_value(),
                access_minutes=settings.access_token_minutes,
                refresh_days=settings.refresh_token_days,
            )
            second = await service.login(email, "long password for test")
            self.assertIn("refresh_token", second)
        async with self.session_factory() as session:
            service = AuthService(
                UserRepository(session),
                secret=settings.jwt_secret_key.get_secret_value(),
                access_minutes=settings.access_token_minutes,
                refresh_days=settings.refresh_token_days,
            )
            rotated = await service.refresh(first["refresh_token"])
            self.assertIn("refresh_token", rotated)
        async with self.session_factory() as session:
            service = AuthService(
                UserRepository(session),
                secret=settings.jwt_secret_key.get_secret_value(),
                access_minutes=settings.access_token_minutes,
                refresh_days=settings.refresh_token_days,
            )
            with self.assertRaises(AuthenticationError):
                await service.refresh(first["refresh_token"])
        async with self.session_factory() as session:
            sessions = list(
                (
                    await session.scalars(
                        select(RefreshSession).where(RefreshSession.user_id == user.id)
                    )
                ).all()
            )
        self.assertEqual(len(sessions), 3)
        self.assertTrue(all(item.revoked_at is not None for item in sessions))

    async def test_expired_revoked_refresh_does_not_revoke_other_sessions(self) -> None:
        secret = "day3-test-signing-secret-at-least-32-bytes"
        email = f"{uuid4().hex}@example.com"
        async with self.session_factory() as session:
            service = AuthService(
                UserRepository(session),
                secret=secret,
                access_minutes=10,
                refresh_days=10,
            )
            user = await service.register(
                email, "Expired Replay", "long password for test"
            )
        async with self.session_factory() as session:
            service = AuthService(
                UserRepository(session),
                secret=secret,
                access_minutes=10,
                refresh_days=10,
            )
            first = await service.login(email, "long password for test")
            second = await service.login(email, "long password for test")
        claims = decode_token(first["refresh_token"], secret)
        expired_at = datetime.now(UTC) - timedelta(seconds=1)
        async with self.session_factory() as session:
            old_session = await session.get(RefreshSession, str(claims["jti"]))
            old_session.revoked_at = expired_at
            old_session.expires_at = expired_at
            await session.commit()
        expired_token, _, _ = create_token(
            secret=secret,
            subject=user.id,
            token_type="refresh",
            expires_in=timedelta(seconds=-1),
            jti=str(claims["jti"]),
        )
        async with self.session_factory() as session:
            service = AuthService(
                UserRepository(session),
                secret=secret,
                access_minutes=10,
                refresh_days=10,
            )
            with self.assertRaises(AuthenticationError):
                await service.refresh(expired_token)
        async with self.session_factory() as session:
            remaining = await session.get(
                RefreshSession,
                str(decode_token(second["refresh_token"], secret)["jti"]),
            )
        self.assertIsNone(remaining.revoked_at)

    async def test_refresh_session_lock_reloads_committed_revocation(self) -> None:
        from datetime import UTC, datetime, timedelta

        from app.models.entities import RefreshSession

        user_id = uuid4()
        jti = str(uuid4())
        async with self.session_factory() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    full_name="Refresh Lock Test",
                    hashed_password="unused-hash",
                )
            )
            await session.flush()
            session.add(
                RefreshSession(
                    jti=jti,
                    user_id=user_id,
                    expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
            await session.commit()

        async with self.session_factory() as first:
            stale = await first.get(RefreshSession, jti)
            await first.commit()
            async with self.session_factory() as second:
                changed = await UserRepository(second).get_refresh_for_update(jti)
                changed.revoked_at = datetime.now(UTC)
                await second.commit()
            refreshed = await UserRepository(first).get_refresh_for_update(jti)
            self.assertIsNotNone(stale.revoked_at)
            self.assertEqual(refreshed.revoked_at, stale.revoked_at)
            await first.rollback()

    async def test_profile_and_password_changes_recheck_active_under_lock(self) -> None:
        profile_user_id = uuid4()
        password_user_id = uuid4()
        current_password = "known current password"
        current_hash = await hash_password_async(current_password)
        async with self.session_factory() as session:
            session.add_all(
                [
                    User(
                        id=profile_user_id,
                        email=f"{profile_user_id}@example.com",
                        full_name="Active Before Race",
                        hashed_password="unused-hash",
                        is_active=True,
                    ),
                    User(
                        id=password_user_id,
                        email=f"{password_user_id}@example.com",
                        full_name="Password Race",
                        hashed_password=current_hash,
                        is_active=True,
                    ),
                ]
            )
            await session.commit()

        async with self.session_factory() as profile_request:
            preloaded = await UserRepository(profile_request).get(profile_user_id)
            async with self.session_factory() as admin_session:
                deactivated = await UserRepository(admin_session).get_for_update(
                    profile_user_id
                )
                deactivated.is_active = False
                await admin_session.commit()

            service = AuthService(
                UserRepository(profile_request),
                secret="database-test-signing-secret-at-least-32-bytes",
                access_minutes=15,
                refresh_days=30,
            )
            with self.assertRaisesRegex(
                AuthenticationError, AUTH_INACTIVE_ACCOUNT_MESSAGE
            ):
                await service.update_profile(preloaded, {"full_name": "Must Not Save"})

        async with self.session_factory() as password_request:
            preloaded = await UserRepository(password_request).get(password_user_id)
            async with self.session_factory() as admin_session:
                deactivated = await UserRepository(admin_session).get_for_update(
                    password_user_id
                )
                deactivated.is_active = False
                await admin_session.commit()
            service = AuthService(
                UserRepository(password_request),
                secret="database-test-signing-secret-at-least-32-bytes",
                access_minutes=15,
                refresh_days=30,
            )
            with self.assertRaisesRegex(
                AuthenticationError, AUTH_INACTIVE_ACCOUNT_MESSAGE
            ):
                await service.change_password(
                    preloaded, current_password, "new password long"
                )

        async with self.session_factory() as session:
            profile_saved = await UserRepository(session).get(profile_user_id)
            password_saved = await UserRepository(session).get(password_user_id)
            self.assertFalse(profile_saved.is_active)
            self.assertEqual(profile_saved.full_name, "Active Before Race")
            self.assertFalse(password_saved.is_active)
            self.assertEqual(password_saved.full_name, "Password Race")

    async def test_migrated_schema_matches_model_metadata(self) -> None:
        async with self.engine.connect() as connection:
            actual = await connection.run_sync(
                lambda sync_connection: {
                    table: {
                        column["name"]
                        for column in inspect(sync_connection).get_columns(table)
                    }
                    for table in inspect(sync_connection).get_table_names()
                    if table != "alembic_version"
                }
            )
        expected = {
            table.name: {column.name for column in table.columns}
            for table in Base.metadata.sorted_tables
        }
        self.assertEqual(actual, expected)

    async def test_legacy_conversion_preserves_data_for_both_revisions(self) -> None:
        for revision in ("552a3882346e", "9e5ac2ec2ba3"):
            schema = f"legacy_{uuid4().hex}"
            connection = await self.engine.connect()
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await create_legacy_fixture(connection, revision)
                await upgrade_legacy_schema(connection)
                full_name = await connection.scalar(
                    text("SELECT full_name FROM users WHERE email = 'old@example.test'")
                )
                values = await connection.execute(
                    text(
                        "SELECT u.hashed_password, p.description, l.project_id, l.color, "
                        "t.created_by, c.content, c.updated_at, tl.created_at "
                        "FROM users u CROSS JOIN projects p CROSS JOIN labels l "
                        "CROSS JOIN tasks t CROSS JOIN comments c CROSS JOIN task_labels tl"
                    )
                )
                row = values.one()
                self.assertEqual(full_name, "Old User")
                self.assertTrue(
                    row.hashed_password.startswith("disabled$pbkdf2_sha256$")
                )
                self.assertEqual(row.description, None)
                self.assertEqual(row.color, "#777777")
                self.assertEqual(row.content, "old comment")
                self.assertIsNotNone(row.project_id)
                self.assertIsNotNone(row.created_by)
                self.assertIsNotNone(row.updated_at)
                self.assertIsNotNone(row.created_at)
                self.assertEqual(
                    await connection.scalar(
                        text("SELECT version_num FROM alembic_version")
                    ),
                    "552a3882346e",
                )
            finally:
                await transaction.rollback()
                await connection.close()

    async def test_legacy_conversion_preserves_existing_full_timestamps(self) -> None:
        schema = f"legacy_{uuid4().hex}"
        async with self.engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await create_legacy_fixture(
                    connection, "552a3882346e", full_timestamps=True
                )
                tables = (
                    "users",
                    "workspaces",
                    "projects",
                    "workspace_members",
                    "tasks",
                    "labels",
                    "task_labels",
                    "comments",
                )
                before = {}
                for table in tables:
                    result = await connection.execute(
                        text(f"SELECT created_at, updated_at FROM {table}")
                    )
                    before[table] = list(result.all())
                await upgrade_legacy_schema(connection)
                after = {}
                for table in tables:
                    result = await connection.execute(
                        text(f"SELECT created_at, updated_at FROM {table}")
                    )
                    after[table] = list(result.all())
                self.assertEqual(after, before)
            finally:
                await transaction.rollback()

    async def test_legacy_conversion_rejects_cross_project_links_before_writes(
        self,
    ) -> None:
        schema = f"legacy_{uuid4().hex}"
        async with self.engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await create_legacy_fixture(
                    connection, "552a3882346e", cross_project_label=True
                )
                with self.assertRaisesRegex(ValueError, "task project differs"):
                    await upgrade_legacy_schema(connection)
                columns = await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'users'"
                    )
                )
                user_columns = {row[0] for row in columns}
                self.assertIn("name", user_columns)
                self.assertNotIn("full_name", user_columns)
                self.assertEqual(
                    await connection.scalar(text("SELECT count(*) FROM task_labels")),
                    1,
                )
            finally:
                await transaction.rollback()
                await connection.close()

    async def test_legacy_conversion_rejects_ambiguous_labels_without_writes(
        self,
    ) -> None:
        schema = f"legacy_{uuid4().hex}"
        async with self.engine.connect() as connection:
            transaction = await connection.begin()
            try:
                await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                await create_legacy_fixture(
                    connection, "552a3882346e", two_projects=True
                )
                with self.assertRaisesRegex(ValueError, "exactly one project"):
                    await upgrade_legacy_schema(connection)
                columns = await connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() AND table_name = 'users'"
                    )
                )
                self.assertIn("name", {row[0] for row in columns})
                self.assertNotIn("full_name", {row[0] for row in columns})
            finally:
                await transaction.rollback()

    async def test_repository_pagination_and_total(self) -> None:
        async with self.session_factory() as session:
            repository = TaskRepository(session)
            for title in ("first", "second", "third"):
                await repository.add(
                    Task(title=title, status=TaskStatus.IN_PROGRESS),
                    project_id=DEFAULT_PROJECT_ID,
                    user_id=DEFAULT_USER_ID,
                )
            await repository.commit()
            items, total = await repository.list(
                project_id=DEFAULT_PROJECT_ID,
                user_id=DEFAULT_USER_ID,
                status=TaskStatus.IN_PROGRESS,
                offset=1,
                limit=1,
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(total, 3)

    async def test_repository_crud_and_nullable_fields(self) -> None:
        async with self.session_factory() as session:
            repository = TaskRepository(session)
            created = await repository.add(
                Task(title="nullable fields"),
                project_id=DEFAULT_PROJECT_ID,
                user_id=DEFAULT_USER_ID,
            )
            await repository.commit()
            stored = await session.get(TaskRow, created.id)
            self.assertIsNone(stored.description)
            self.assertIsNone(stored.assignee_id)
            self.assertIsNone(stored.due_date)
            found = await repository.get_for_update(
                created.id, user_id=DEFAULT_USER_ID
            )
            self.assertEqual(found.title, "nullable fields")
            found.title = "updated title"
            found.description = None
            found.touch()
            saved = await repository.save(found)
            await repository.commit()
            self.assertEqual(saved.title, "updated title")
            await repository.delete(created.id, user_id=DEFAULT_USER_ID)
            await repository.commit()
            with self.assertRaises(TaskNotFoundError):
                await repository.get(created.id, user_id=DEFAULT_USER_ID)

    async def test_save_missing_task_raises_not_found(self) -> None:
        async with self.session_factory() as session:
            repository = TaskRepository(session)
            with self.assertRaises(TaskNotFoundError):
                await repository.save(Task(id=uuid4(), title="missing"))

    async def test_concurrent_updates_preserve_both_fields(self) -> None:
        async with self.session_factory() as session:
            repository = TaskRepository(session)
            task = await repository.add(
                Task(title="concurrent"),
                project_id=DEFAULT_PROJECT_ID,
                user_id=DEFAULT_USER_ID,
            )
            await repository.commit()

        first_locked = asyncio.Event()
        release_first = asyncio.Event()

        async def update_description() -> None:
            async with self.session_factory() as session:
                repository = TaskRepository(session)
                current = await repository.get_for_update(
                    task.id, user_id=DEFAULT_USER_ID
                )
                first_locked.set()
                await release_first.wait()
                current.description = "description retained"
                current.touch()
                await repository.save(current)
                await repository.commit()

        async def update_status() -> None:
            await first_locked.wait()
            async with self.session_factory() as session:
                repository = TaskRepository(session)
                current = await repository.get_for_update(
                    task.id, user_id=DEFAULT_USER_ID
                )
                current.status = TaskStatus.IN_PROGRESS
                current.touch()
                await repository.save(current)
                await repository.commit()

        first = asyncio.create_task(update_description())
        second = asyncio.create_task(update_status())
        await first_locked.wait()
        await asyncio.sleep(0)
        release_first.set()
        await asyncio.wait_for(asyncio.gather(first, second), timeout=5)

        async with self.session_factory() as session:
            current = await TaskRepository(session).get(
                task.id, user_id=DEFAULT_USER_ID
            )

        self.assertEqual(current.description, "description retained")
        self.assertEqual(current.status, TaskStatus.IN_PROGRESS)

    async def test_project_archive_serializes_with_task_write(self) -> None:
        async with self.session_factory() as session:
            project = Project(
                workspace_id=DEFAULT_WORKSPACE_ID, name="Archive lock"
            )
            session.add(project)
            await session.flush()
            task = await TaskRepository(session).add(
                Task(title="archive lock"),
                project_id=project.id,
                user_id=DEFAULT_USER_ID,
            )
            await session.commit()

        project_locked = asyncio.Event()
        archive_now = asyncio.Event()
        writer_pid_ready = asyncio.Event()
        writer_pid: int | None = None

        async def archive_project() -> None:
            async with self.session_factory() as session:
                locked_project = await session.scalar(
                    select(Project)
                    .where(Project.id == project.id)
                    .with_for_update()
                )
                project_locked.set()
                await archive_now.wait()
                locked_project.status = ProjectStatus.ARCHIVED
                await session.commit()

        async def attempt_update() -> bool:
            nonlocal writer_pid
            async with self.session_factory() as session:
                writer_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                writer_pid_ready.set()
                try:
                    await TaskService(TaskRepository(session)).update(
                        task.id, TaskUpdate(title="must not commit"), DEFAULT_USER_ID
                    )
                except ProjectArchivedError:
                    return True
                return False

        archiver = asyncio.create_task(archive_project())
        await project_locked.wait()
        writer = asyncio.create_task(attempt_update())
        await writer_pid_ready.wait()
        self.assertIsNotNone(writer_pid)
        await wait_for_database_lock(self.session_factory, writer_pid)
        archive_now.set()
        self.assertTrue(await asyncio.wait_for(writer, timeout=5))
        await asyncio.wait_for(archiver, timeout=5)

        async with self.session_factory() as session:
            saved = await session.get(TaskRow, task.id)
            self.assertEqual(saved.title, "archive lock")
            await session.delete(await session.get(Project, project.id))
            await session.commit()

    async def test_membership_revocation_serializes_with_task_write(self) -> None:
        user_id = uuid4()
        async with self.session_factory() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"revoked-{user_id.hex}@example.test",
                    full_name="Revoked editor",
                    hashed_password="unused",
                )
            )
            await session.flush()
            membership = WorkspaceMember(
                workspace_id=DEFAULT_WORKSPACE_ID,
                user_id=user_id,
                role=WorkspaceRole.EDITOR,
            )
            session.add(membership)
            task = await TaskRepository(session).add(
                Task(title="membership lock"),
                project_id=DEFAULT_PROJECT_ID,
                user_id=DEFAULT_USER_ID,
            )
            await session.commit()

        membership_locked = asyncio.Event()
        revoke_now = asyncio.Event()
        writer_pid_ready = asyncio.Event()
        writer_pid: int | None = None

        async def revoke_membership() -> None:
            async with self.session_factory() as session:
                member = await session.scalar(
                    select(WorkspaceMember)
                    .where(
                        WorkspaceMember.workspace_id == DEFAULT_WORKSPACE_ID,
                        WorkspaceMember.user_id == user_id,
                    )
                    .with_for_update()
                )
                membership_locked.set()
                await revoke_now.wait()
                await session.delete(member)
                await session.commit()

        async def attempt_write() -> bool:
            nonlocal writer_pid
            async with self.session_factory() as session:
                writer_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                writer_pid_ready.set()
                try:
                    await TaskService(TaskRepository(session)).update(
                        task.id, TaskUpdate(title="must roll back"), user_id
                    )
                except TaskNotFoundError:
                    return True
                return False

        revoker = asyncio.create_task(revoke_membership())
        await membership_locked.wait()
        writer = asyncio.create_task(attempt_write())
        await writer_pid_ready.wait()
        self.assertIsNotNone(writer_pid)
        await wait_for_database_lock(self.session_factory, writer_pid)
        revoke_now.set()
        self.assertTrue(await asyncio.wait_for(writer, timeout=5))
        await asyncio.wait_for(revoker, timeout=5)
        async with self.session_factory() as session:
            saved = await session.get(TaskRow, task.id)
        self.assertEqual(saved.title, "membership lock")

    async def test_ownership_transfer_serializes_with_task_write(self) -> None:
        old_owner = User(
            email=f"old-owner-{uuid4().hex}@example.test",
            full_name="Old owner",
            hashed_password="unused",
        )
        new_owner = User(
            email=f"new-owner-{uuid4().hex}@example.test",
            full_name="New owner",
            hashed_password="unused",
        )
        workspace = Workspace(name="Ownership transfer", owner=old_owner)
        project = Project(name="Transfer project", workspace=workspace)
        async with self.session_factory() as session:
            session.add_all([old_owner, new_owner, workspace, project])
            await session.flush()
            task = TaskRow(
                project_id=project.id,
                title="ownership lock",
                created_by=old_owner.id,
            )
            session.add(task)
            await session.commit()

        workspace_locked = asyncio.Event()
        transfer_now = asyncio.Event()
        writer_pid_ready = asyncio.Event()
        writer_pid: int | None = None

        async def transfer_ownership() -> None:
            async with self.session_factory() as session:
                locked_workspace = await session.scalar(
                    select(Workspace)
                    .where(Workspace.id == workspace.id)
                    .with_for_update()
                )
                workspace_locked.set()
                await transfer_now.wait()
                locked_workspace.owner_id = new_owner.id
                await session.commit()

        async def attempt_write() -> bool:
            nonlocal writer_pid
            async with self.session_factory() as session:
                writer_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                writer_pid_ready.set()
                try:
                    await TaskService(TaskRepository(session)).update(
                        task.id, TaskUpdate(title="must roll back"), old_owner.id
                    )
                except TaskNotFoundError:
                    return True
                return False

        transfer = asyncio.create_task(transfer_ownership())
        await workspace_locked.wait()
        writer = asyncio.create_task(attempt_write())
        await writer_pid_ready.wait()
        self.assertIsNotNone(writer_pid)
        await wait_for_database_lock(self.session_factory, writer_pid)
        transfer_now.set()
        self.assertTrue(await asyncio.wait_for(writer, timeout=5))
        await asyncio.wait_for(transfer, timeout=5)
        async with self.session_factory() as session:
            saved = await session.get(TaskRow, task.id)
        self.assertEqual(saved.title, "ownership lock")

    async def test_delete_cascades_task_comments_and_labels(self) -> None:
        async with self.session_factory() as session:
            repository = TaskRepository(session)
            task = await repository.add(
                Task(title="cascade"),
                project_id=DEFAULT_PROJECT_ID,
                user_id=DEFAULT_USER_ID,
            )
            label = Label(project_id=DEFAULT_PROJECT_ID, name="test", color="#777777")
            session.add(label)
            await session.flush()
            session.add_all(
                [
                    TaskLabel(task_id=task.id, label_id=label.id),
                    Comment(
                        task_id=task.id,
                        author_id=DEFAULT_USER_ID,
                        content="test comment",
                    ),
                ]
            )
            await repository.commit()
            await repository.delete(task.id, user_id=DEFAULT_USER_ID)
            await repository.commit()
            comments = await session.scalar(
                select(func.count())
                .select_from(Comment)
                .where(Comment.task_id == task.id)
            )
            labels = await session.scalar(
                select(func.count())
                .select_from(TaskLabel)
                .where(TaskLabel.task_id == task.id)
            )

        self.assertEqual(comments, 0)
        self.assertEqual(labels, 0)

    async def test_all_models_have_utc_audit_timestamps(self) -> None:
        async with self.session_factory() as session:
            repository = TaskRepository(session)
            domain_task = await repository.add(
                Task(title="timestamps"),
                project_id=DEFAULT_PROJECT_ID,
                user_id=DEFAULT_USER_ID,
            )
            label = Label(
                project_id=DEFAULT_PROJECT_ID, name="timestamps", color="#777777"
            )
            session.add(label)
            await session.flush()
            association = TaskLabel(task_id=domain_task.id, label_id=label.id)
            comment = Comment(
                task_id=domain_task.id,
                author_id=DEFAULT_USER_ID,
                content="timestamps",
            )
            session.add_all([association, comment])
            await session.commit()

            models = [
                await session.get(User, DEFAULT_USER_ID),
                await session.get(Workspace, DEFAULT_WORKSPACE_ID),
                await session.get(
                    WorkspaceMember, (DEFAULT_WORKSPACE_ID, DEFAULT_USER_ID)
                ),
                await session.get(Project, DEFAULT_PROJECT_ID),
                await session.get(TaskRow, domain_task.id),
                await session.get(Label, label.id),
                await session.get(TaskLabel, (domain_task.id, label.id)),
                await session.get(Comment, comment.id),
            ]

        for model in models:
            with self.subTest(model=type(model).__name__):
                self.assertEqual(model.created_at.utcoffset().total_seconds(), 0)
                self.assertEqual(model.updated_at.utcoffset().total_seconds(), 0)

    async def test_real_asyncpg_foreign_key_status_mapping(self) -> None:
        bad_task = TaskRow(
            project_id=DEFAULT_PROJECT_ID,
            title="invalid creator",
            created_by=uuid4(),
        )
        async with self.session_factory() as session:
            session.add(bad_task)
            with self.assertRaises(IntegrityError) as caught:
                await session.flush()
            self.assertEqual(
                integrity_error_response(
                    request_for("POST"), caught.exception
                ).status_code,
                422,
            )
            await session.rollback()
            remaining = await session.scalar(
                select(func.count())
                .select_from(TaskRow)
                .where(TaskRow.title == "invalid creator")
            )
            self.assertEqual(remaining, 0)

        creator_id = uuid4()
        async with self.session_factory() as session:
            creator = User(
                id=creator_id,
                email=f"{creator_id}@taskhub.local",
                full_name="Temporary creator",
                hashed_password="disabled$test",
            )
            session.add(creator)
            await session.flush()
            task = TaskRow(
                project_id=DEFAULT_PROJECT_ID,
                title="restricted creator",
                created_by=creator_id,
            )
            session.add(task)
            await session.commit()
            await session.delete(creator)
            with self.assertRaises(IntegrityError) as caught:
                await session.flush()
            self.assertEqual(
                integrity_error_response(
                    request_for("DELETE"), caught.exception
                ).status_code,
                409,
            )
            await session.rollback()
