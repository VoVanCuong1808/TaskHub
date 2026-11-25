"""Focused PostgreSQL integration tests for project lifecycle behavior."""

import asyncio
import os
import subprocess
import sys
import unittest
from datetime import UTC, datetime
from uuid import UUID

from fastapi.testclient import TestClient
from pydantic import RedisDsn
from sqlalchemy import delete, event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import tests.test_postgres as postgres_tests
from app.core.config import Settings
from app.core.exceptions import ProjectArchivedError
from app.db.project_uow import SQLAlchemyProjectUnitOfWork
from app.db.seed import seed_default_data
from app.db.task_uow import SQLAlchemyTaskManagementUnitOfWork
from app.main import create_app
from app.models.entities import (
    Comment,
    Label,
    Project,
    TaskLabel,
    User,
    WorkspaceMember,
)
from app.models.entities import (
    Task as TaskRow,
)
from app.models.enums import (
    ProjectStatus,
    WorkspaceRole,
)
from app.repositories.project_repository import ProjectRepository
from app.services.project_service import ProjectService
from app.services.task_service import TaskService
from tests.test_postgres import (
    ROOT,
    TEST_DATABASE_ENV,
    isolated_test_settings,
    wait_for_database_lock,
)


class ProjectPostgreSQLTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        test_url = os.environ.get(TEST_DATABASE_ENV)
        if not test_url:
            raise unittest.SkipTest(f"Set {TEST_DATABASE_ENV} to taskhub_test")
        from sqlalchemy.engine import make_url

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

    async def _make_workspace_fixture(self):
        return await postgres_tests.PostgreSQLTests._make_workspace_fixture(self)

    async def _make_task_auth_fixture(self):
        return await postgres_tests.PostgreSQLTests._make_task_auth_fixture(self)

    def _workspace_headers(self, user: User, secret: str) -> dict[str, str]:
        return postgres_tests.PostgreSQLTests._workspace_headers(user, secret)

    def _task_auth_headers(self, user: User, secret: str) -> dict[str, str]:
        return postgres_tests.PostgreSQLTests._task_auth_headers(self, user, secret)

    def _workspace_settings(self, secret: str) -> Settings:
        return isolated_test_settings(self.test_url, secret)

    def _task_auth_settings(self) -> Settings:
        return isolated_test_settings(
            self.test_url,
            "day4-test-signing-secret-at-least-32-bytes",
        )

    async def test_project_crud_permissions_pagination_archive_and_delete_cascade(self) -> None:
        data = await self._make_workspace_fixture()
        owner_headers = self._workspace_headers(data.owner, data.secret)
        editor_headers = self._workspace_headers(data.editor, data.secret)
        viewer_headers = self._workspace_headers(data.viewer, data.secret)
        outsider_headers = self._workspace_headers(data.outsider, data.secret)
        admin_headers = self._workspace_headers(data.admin, data.secret)
        project_path = f"/api/v1/workspaces/{data.workspace.id}/projects"
        async with self.session_factory() as session:
            session.add(
                WorkspaceMember(
                    workspace_id=data.workspace.id,
                    user_id=data.stale_owner.id,
                    role=WorkspaceRole.OWNER,
                )
            )
            await session.commit()
        stale_owner_headers = self._workspace_headers(data.stale_owner, data.secret)

        with TestClient(create_app(self._workspace_settings(data.secret))) as client:
            created = client.post(
                project_path,
                headers=editor_headers,
                json={"name": "Delivery Project", "description": "project details"},
            )
            self.assertEqual(created.status_code, 201, created.text)
            project_id = UUID(created.json()["id"])
            self.assertEqual(created.json()["status"], "active")
            self.assertEqual(created.json()["workspace_id"], str(data.workspace.id))

            second = client.post(
                project_path, headers=owner_headers, json={"name": "Second Project"}
            )
            self.assertEqual(second.status_code, 201, second.text)
            second_id = UUID(second.json()["id"])

            for actor_headers in (viewer_headers, stale_owner_headers):
                self.assertEqual(
                    client.post(project_path, headers=actor_headers, json={"name": "Denied"}).status_code,
                    403,
                )
            for actor_headers in (outsider_headers, admin_headers):
                self.assertEqual(
                    client.get(project_path, headers=actor_headers).status_code, 404
                )

            async with self.session_factory() as session:
                tie = datetime(2026, 1, 1, tzinfo=UTC)
                for item_id in (data.project.id, project_id, second_id):
                    row = await session.get(Project, item_id)
                    row.created_at = tie
                    row.updated_at = tie
                await session.commit()
            expected_order = sorted(
                (data.project.id, project_id, second_id), reverse=True
            )
            statement_count = []

            def count_select(*_args) -> None:
                statement_count.append(None)

            event.listen(self.engine.sync_engine, "before_cursor_execute", count_select)
            try:
                async with self.session_factory() as session:
                    empty_page, total = await ProjectRepository(session).list(
                        data.workspace.id, offset=3, limit=1
                    )
            finally:
                event.remove(
                    self.engine.sync_engine, "before_cursor_execute", count_select
                )
            self.assertEqual((empty_page, total), ([], 3))
            self.assertEqual(len(statement_count), 1)

            pages = [
                client.get(project_path, headers=viewer_headers, params={"page": page, "limit": 1})
                for page in (1, 2, 3)
            ]
            self.assertEqual([r.json()["items"][0]["id"] for r in pages], [str(i) for i in expected_order])
            out_of_range = client.get(
                project_path, headers=viewer_headers, params={"page": 4, "limit": 1}
            )
            self.assertEqual(out_of_range.json(), {"items": [], "total": 3})
            self.assertEqual(
                client.get(project_path, headers=viewer_headers, params={"offset": 0}).status_code,
                422,
            )

            endpoint = f"/api/v1/projects/{project_id}"
            self.assertEqual(client.get(endpoint, headers=viewer_headers).status_code, 200)
            self.assertEqual(client.get(endpoint, headers=stale_owner_headers).status_code, 200)
            self.assertEqual(
                client.patch(endpoint, headers=viewer_headers, json={"name": "Denied"}).status_code,
                403,
            )
            self.assertEqual(
                client.patch(endpoint, headers=stale_owner_headers, json={"name": "Denied"}).status_code,
                403,
            )
            archived = client.patch(endpoint, headers=editor_headers, json={"status": "archived"})
            self.assertEqual(archived.status_code, 200, archived.text)
            self.assertEqual(archived.json()["status"], "archived")
            self.assertEqual(client.get(endpoint, headers=viewer_headers).status_code, 200)
            self.assertEqual(
                client.post(
                    "/api/v1/tasks",
                    headers=editor_headers,
                    json={"project_id": str(project_id), "title": "blocked while archived"},
                ).status_code,
                409,
            )
            restored = client.patch(endpoint, headers=editor_headers, json={"status": "active"})
            self.assertEqual(restored.status_code, 200, restored.text)

            task_response = client.post(
                "/api/v1/tasks",
                headers=editor_headers,
                json={"project_id": str(project_id), "title": "Cascade task"},
            )
            self.assertEqual(task_response.status_code, 201, task_response.text)
            task_id = UUID(task_response.json()["id"])
            label_response = client.post(
                "/api/v1/labels",
                headers=editor_headers,
                json={"project_id": str(project_id), "name": "Cascade label", "color": "blue"},
            )
            self.assertEqual(label_response.status_code, 201, label_response.text)
            label_id = UUID(label_response.json()["id"])
            linked = client.put(
                f"/api/v1/tasks/{task_id}/labels/{label_id}", headers=editor_headers
            )
            self.assertEqual(linked.status_code, 204, linked.text)
            comment_response = client.post(
                f"/api/v1/tasks/{task_id}/comments",
                headers=editor_headers,
                json={"content": "cascade comment"},
            )
            self.assertEqual(comment_response.status_code, 201, comment_response.text)
            comment_id = UUID(comment_response.json()["id"])
            editor_delete = client.delete(endpoint, headers=editor_headers)
            self.assertEqual(editor_delete.status_code, 403, editor_delete.text)
            self.assertEqual(client.get(endpoint, headers=owner_headers).status_code, 200)
            deleted = client.delete(endpoint, headers=owner_headers)
            self.assertEqual(deleted.status_code, 204, deleted.text)
            self.assertEqual(client.get(endpoint, headers=owner_headers).status_code, 404)

        async with self.session_factory() as session:
            self.assertIsNone(await session.get(Project, project_id))
            self.assertIsNone(await session.get(TaskRow, task_id))
            self.assertIsNone(await session.get(Label, label_id))
            self.assertIsNone(await session.get(TaskLabel, (task_id, label_id)))
            self.assertIsNone(await session.get(Comment, comment_id))

    @unittest.skipUnless(
        os.getenv(TEST_DATABASE_ENV) and os.getenv("TASKHUB_TEST_REDIS_URL"),
        "requires disposable PostgreSQL and TASKHUB_TEST_REDIS_URL",
    )
    async def test_project_cache_rotation_and_deleted_project_cannot_use_warm_task_cache(self) -> None:
        from redis.asyncio import Redis

        data = await self._make_workspace_fixture()
        redis_url = os.environ["TASKHUB_TEST_REDIS_URL"]
        project_keys = f"taskhub:task-list:v1:project:{data.project.id}:*"
        cleanup = Redis.from_url(redis_url, socket_connect_timeout=0.5, socket_timeout=0.5)
        settings = self._workspace_settings(data.secret).model_copy(
            update={"redis_url": RedisDsn(redis_url)}
        )
        generation_key = f"taskhub:task-list:v1:project:{data.project.id}:generation"
        try:
            with TestClient(create_app(settings)) as client:
                headers = self._workspace_headers(data.owner, data.secret)
                params = {"project_id": str(data.project.id)}
                warmed = client.get("/api/v1/tasks", params=params, headers=headers)
                self.assertEqual(warmed.status_code, 200, warmed.text)
                self.assertTrue(await cleanup.exists(generation_key))
                before_update = await cleanup.get(generation_key)

                updated = client.patch(
                    f"/api/v1/projects/{data.project.id}",
                    headers=headers,
                    json={"name": "Updated project"},
                )
                self.assertEqual(updated.status_code, 200, updated.text)
                after_update = await cleanup.get(generation_key)
                self.assertNotEqual(after_update, before_update)

                self.assertEqual(
                    client.get("/api/v1/tasks", params=params, headers=headers).status_code,
                    200,
                )
                before_delete = await cleanup.get(generation_key)
                deleted = client.delete(
                    f"/api/v1/projects/{data.project.id}", headers=headers
                )
                self.assertEqual(deleted.status_code, 204, deleted.text)
                after_delete = await cleanup.get(generation_key)
                self.assertNotEqual(after_delete, before_delete)
                self.assertEqual(
                    client.get("/api/v1/tasks", params=params, headers=headers).status_code,
                    404,
                )
        finally:
            async for key in cleanup.scan_iter(match=project_keys):
                await cleanup.delete(key)
            await cleanup.aclose()

    async def test_project_archive_waits_for_task_write_holding_project_share_lock(self) -> None:
        data = await self._make_task_auth_fixture()
        project_shared = asyncio.Event()
        release_task_write = asyncio.Event()
        archive_started = asyncio.Event()
        archive_pid = None

        async def create_task_while_paused():
            async with self.session_factory() as session:
                uow = SQLAlchemyTaskManagementUnitOfWork(session)
                original_get_for_share = uow.projects.get_for_share

                async def pause_after_project_share(project_id):
                    project = await original_get_for_share(project_id)
                    project_shared.set()
                    await release_task_write.wait()
                    return project

                uow.projects.get_for_share = pause_after_project_share
                return await TaskService(uow).create(
                    project_id=data.project.id,
                    user_id=data.owner.id,
                    title="committed before archive",
                )

        async def archive_project():
            nonlocal archive_pid
            async with self.session_factory() as session:
                archive_pid = await session.scalar(text("SELECT pg_backend_pid()"))
                archive_started.set()
                return await ProjectService(
                    SQLAlchemyProjectUnitOfWork(session)
                ).update(
                    data.project.id,
                    {"status": ProjectStatus.ARCHIVED},
                    data.owner.id,
                )

        task_writer = asyncio.create_task(create_task_while_paused())
        archiver = None
        try:
            await asyncio.wait_for(project_shared.wait(), timeout=5)
            archiver = asyncio.create_task(archive_project())
            await asyncio.wait_for(archive_started.wait(), timeout=5)
            self.assertIsNotNone(archive_pid)
            await wait_for_database_lock(self.session_factory, archive_pid)
        finally:
            release_task_write.set()
        created = await asyncio.wait_for(task_writer, timeout=5)
        archived = await asyncio.wait_for(archiver, timeout=5)
        self.assertEqual(created.title, "committed before archive")
        self.assertEqual(archived.status, ProjectStatus.ARCHIVED)

        async with self.session_factory() as session:
            with self.assertRaises(ProjectArchivedError):
                await TaskService(SQLAlchemyTaskManagementUnitOfWork(session)).create(
                    project_id=data.project.id,
                    user_id=data.owner.id,
                    title="rejected after archive",
                )
