"""PostgreSQL repository and migration integration tests."""

import asyncio
import os
import subprocess
import sys
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, func, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.core.config import Settings
from app.core.constants import AUTH_INACTIVE_ACCOUNT_MESSAGE
from app.core.exceptions import AuthenticationError, TaskNotFoundError
from app.core.security import create_token, decode_token, hash_password_async
from app.db.base import Base
from app.db.legacy_upgrade import upgrade_legacy_schema
from app.db.seed import (
    DEFAULT_PROJECT_ID,
    DEFAULT_USER_ID,
    DEFAULT_WORKSPACE_ID,
    seed_default_data,
)
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
from app.models.enums import TaskStatus
from app.models.task import Task
from app.repositories.task_database import TaskRepository
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService

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

    async def test_user_for_update_refreshes_preloaded_password_hash(self) -> None:
        user_id = uuid4()
        async with self.session_factory() as session:
            session.add(
                User(
                    id=user_id,
                    email=f"{user_id}@example.com",
                    full_name="Lock Test",
                    hashed_password="old-hash",
                )
            )
            await session.commit()

        async with self.session_factory() as first, self.session_factory() as second:
            preloaded = await first.get(User, user_id)
            current = await UserRepository(second).get_for_update(user_id)
            current.hashed_password = "new-hash"
            await second.commit()
            locked = await UserRepository(first).get_by_email_for_update(
                f"{user_id}@example.com"
            )
            self.assertEqual(preloaded.hashed_password, "new-hash")
            self.assertEqual(locked.hashed_password, "new-hash")
            await first.rollback()

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
                await repository.add(Task(title=title, status=TaskStatus.IN_PROGRESS))
            await repository.commit()
            items, total = await repository.list(
                status=TaskStatus.IN_PROGRESS, offset=1, limit=1
            )

        self.assertEqual(len(items), 1)
        self.assertEqual(total, 3)

    async def test_repository_crud_and_nullable_fields(self) -> None:
        async with self.session_factory() as session:
            repository = TaskRepository(session)
            created = await repository.add(Task(title="nullable fields"))
            await repository.commit()
            stored = await session.get(TaskRow, created.id)
            self.assertIsNone(stored.description)
            self.assertIsNone(stored.assignee_id)
            self.assertIsNone(stored.due_date)
            found = await repository.get(created.id)
            self.assertEqual(found.title, "nullable fields")
            found.title = "updated title"
            found.description = None
            found.touch()
            saved = await repository.save(found)
            await repository.commit()
            self.assertEqual(saved.title, "updated title")
            self.assertTrue(await repository.delete(created.id))
            await repository.commit()
            self.assertIsNone(await repository.get(created.id))
            self.assertFalse(await repository.delete(created.id))

    async def test_save_missing_task_raises_not_found(self) -> None:
        async with self.session_factory() as session:
            repository = TaskRepository(session)
            with self.assertRaises(TaskNotFoundError):
                await repository.save(Task(id=uuid4(), title="missing"))

    async def test_concurrent_updates_preserve_both_fields(self) -> None:
        async with self.session_factory() as session:
            repository = TaskRepository(session)
            task = await repository.add(Task(title="concurrent"))
            await repository.commit()

        first_locked = asyncio.Event()
        release_first = asyncio.Event()

        async def update_description() -> None:
            async with self.session_factory() as session:
                repository = TaskRepository(session)
                current = await repository.get_for_update(task.id)
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
                current = await repository.get_for_update(task.id)
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
            current = await TaskRepository(session).get(task.id)

        self.assertEqual(current.description, "description retained")
        self.assertEqual(current.status, TaskStatus.IN_PROGRESS)

    async def test_delete_cascades_task_comments_and_labels(self) -> None:
        async with self.session_factory() as session:
            repository = TaskRepository(session)
            task = await repository.add(Task(title="cascade"))
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
            self.assertTrue(await repository.delete(task.id))
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
            domain_task = await repository.add(Task(title="timestamps"))
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
