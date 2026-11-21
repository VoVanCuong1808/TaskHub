"""Project use-case tests at the repository and cache ports."""

import unittest
from datetime import UTC, datetime
from uuid import uuid4

from app.core.exceptions import PermissionDeniedError, ProjectNotFoundError
from app.models.entities import Project, Workspace, WorkspaceMember
from app.models.enums import ProjectStatus, WorkspaceRole
from app.services.project_service import ProjectService


class FakeProjectStore:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.items: dict[object, Project] = {}
        self.locked_project: Project | None = None
        self.update_error: Exception | None = None

    async def add(self, project: Project) -> Project:
        self.events.append("add_project")
        project.id = project.id or uuid4()
        now = datetime.now(UTC)
        project.created_at = project.created_at or now
        project.updated_at = project.updated_at or now
        self.items[project.id] = project
        return project

    async def get(self, project_id):
        self.events.append("get_project")
        return self.items.get(project_id)

    async def get_for_share(self, project_id):
        self.events.append("share_project")
        return self.items.get(project_id)

    async def get_for_update(self, project_id):
        self.events.append("lock_project")
        if self.locked_project is not None:
            return self.locked_project
        return self.items.get(project_id)

    async def list(self, workspace_id, *, offset, limit):
        self.events.append("list_projects")
        items = sorted(
            (p for p in self.items.values() if p.workspace_id == workspace_id),
            key=lambda p: (p.created_at, p.id),
            reverse=True,
        )
        return items[offset : offset + limit], len(items)

    async def update(self, project, *, name, description, status):
        self.events.append("update_project")
        if self.update_error is not None:
            raise self.update_error
        project.name = name
        project.description = description
        project.status = status
        project.updated_at = datetime.now(UTC)
        return project

    async def delete(self, project):
        self.events.append("delete_project")
        self.items.pop(project.id, None)


class FakeWorkspaceStore:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.items: dict[object, Workspace] = {}
        self.members: dict[tuple[object, object], WorkspaceMember] = {}

    async def get(self, workspace_id):
        self.events.append("get_workspace")
        return self.items.get(workspace_id)

    async def get_for_share(self, workspace_id):
        self.events.append("share_workspace")
        return self.items.get(workspace_id)

    async def get_member(self, workspace_id, user_id):
        self.events.append("get_member")
        return self.members.get((workspace_id, user_id))

    async def get_member_for_share(self, workspace_id, user_id):
        self.events.append("share_member")
        return self.members.get((workspace_id, user_id))


class FakeProjectUnitOfWork:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.projects = FakeProjectStore(self.events)
        self.workspaces = FakeWorkspaceStore(self.events)
        self.commit_count = 0
        self.rollback_count = 0
        self.commit_error: Exception | None = None

    async def commit(self) -> None:
        self.events.append("commit")
        self.commit_count += 1
        if self.commit_error is not None:
            raise self.commit_error

    async def rollback(self) -> None:
        self.events.append("rollback")
        self.rollback_count += 1


class FakeTaskListCache:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.rotated: list[object] = []
        self.rotate_error: Exception | None = None

    async def rotate(self, project_id) -> None:
        self.events.append("rotate_cache")
        if self.rotate_error is not None:
            raise self.rotate_error
        self.rotated.append(project_id)


class ProjectServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.owner_id = uuid4()
        self.editor_id = uuid4()
        self.viewer_id = uuid4()
        self.stale_owner_id = uuid4()
        self.outsider_id = uuid4()
        self.admin_id = uuid4()
        self.workspace = Workspace(id=uuid4(), name="Workspace", owner_id=self.owner_id)
        self.uow = FakeProjectUnitOfWork()
        self.uow.workspaces.items[self.workspace.id] = self.workspace
        for user_id, role in (
            (self.editor_id, WorkspaceRole.EDITOR),
            (self.viewer_id, WorkspaceRole.VIEWER),
            (self.stale_owner_id, WorkspaceRole.OWNER),
        ):
            self.uow.workspaces.members[(self.workspace.id, user_id)] = WorkspaceMember(
                workspace_id=self.workspace.id, user_id=user_id, role=role
            )
        self.project = Project(
            id=uuid4(),
            workspace_id=self.workspace.id,
            name="Initial",
            description="details",
            status=ProjectStatus.ACTIVE,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        self.uow.projects.items[self.project.id] = self.project
        self.cache = FakeTaskListCache(self.uow.events)
        self.service = ProjectService(self.uow, self.cache)

    async def test_editor_can_create_and_create_locks_parent_before_membership(self) -> None:
        created = await self.service.create(
            workspace_id=self.workspace.id,
            user_id=self.editor_id,
            name="New project",
        )
        self.assertEqual(created.status, ProjectStatus.ACTIVE)
        self.assertLess(self.uow.events.index("share_workspace"), self.uow.events.index("share_member"))
        self.assertLess(self.uow.events.index("share_member"), self.uow.events.index("add_project"))
        self.assertLess(self.uow.events.index("add_project"), self.uow.events.index("commit"))
        self.assertEqual(self.cache.rotated, [])

    async def test_viewers_and_stale_owners_read_but_cannot_write(self) -> None:
        for actor_id in (self.viewer_id, self.stale_owner_id):
            with self.subTest(actor=actor_id):
                self.assertEqual(
                    (await self.service.get(self.project.id, actor_id)).name, "Initial"
                )
                with self.assertRaises(PermissionDeniedError):
                    await self.service.update(self.project.id, {"name": "Denied"}, actor_id)

    async def test_admin_and_outsider_remain_hidden_like_a_missing_project(self) -> None:
        missing_id = uuid4()
        for actor_id in (self.admin_id, self.outsider_id):
            with self.subTest(actor=actor_id):
                with self.assertRaises(ProjectNotFoundError):
                    await self.service.get(self.project.id, actor_id)
                with self.assertRaises(ProjectNotFoundError):
                    await self.service.get(missing_id, actor_id)

    async def test_editor_can_archive_restore_and_delete_with_post_commit_cache_rotation(self) -> None:
        archived = await self.service.update(
            self.project.id, {"status": ProjectStatus.ARCHIVED}, self.editor_id
        )
        self.assertEqual(archived.status, ProjectStatus.ARCHIVED)
        self.assertEqual(self.cache.rotated, [self.project.id])
        self.assertLess(self.uow.events.index("share_workspace"), self.uow.events.index("share_member"))
        self.assertLess(self.uow.events.index("share_member"), self.uow.events.index("lock_project"))
        self.assertLess(self.uow.events.index("lock_project"), self.uow.events.index("update_project"))
        self.assertLess(self.uow.events.index("update_project"), self.uow.events.index("commit"))
        self.assertLess(self.uow.events.index("commit"), self.uow.events.index("rotate_cache"))

        self.uow.events.clear()
        restored = await self.service.update(
            self.project.id,
            {"status": ProjectStatus.ACTIVE, "description": None},
            self.owner_id,
        )
        self.assertEqual(restored.status, ProjectStatus.ACTIVE)
        self.assertIsNone(restored.description)
        self.assertEqual(self.cache.rotated, [self.project.id, self.project.id])

        self.uow.events.clear()
        await self.service.delete(self.project.id, self.editor_id)
        self.assertNotIn(self.project.id, self.uow.projects.items)
        self.assertEqual(self.cache.rotated[-1], self.project.id)
        self.assertLess(self.uow.events.index("commit"), self.uow.events.index("rotate_cache"))

    async def test_archived_project_can_still_be_read_and_metadata_updated(self) -> None:
        self.project.status = ProjectStatus.ARCHIVED
        self.assertEqual((await self.service.get(self.project.id, self.viewer_id)).status, ProjectStatus.ARCHIVED)
        renamed = await self.service.update(
            self.project.id, {"name": "Archived project"}, self.editor_id
        )
        self.assertEqual(renamed.name, "Archived project")

    async def test_partial_update_uses_refreshed_locked_project_and_rechecks_parent(self) -> None:
        refreshed = Project(
            id=self.project.id,
            workspace_id=self.workspace.id,
            name="Concurrent name",
            description="Concurrent description",
            status=ProjectStatus.ARCHIVED,
            created_at=self.project.created_at,
            updated_at=datetime(2026, 2, 1, tzinfo=UTC),
        )
        self.uow.projects.locked_project = refreshed

        updated = await self.service.update(
            self.project.id, {"name": "Requested name"}, self.owner_id
        )
        self.assertEqual(updated.name, "Requested name")
        self.assertEqual(updated.description, "Concurrent description")
        self.assertEqual(updated.status, ProjectStatus.ARCHIVED)

        self.uow.projects.locked_project = Project(
            id=self.project.id,
            workspace_id=uuid4(),
            name="Moved project",
            status=ProjectStatus.ACTIVE,
        )
        rotations_before = len(self.cache.rotated)
        with self.assertRaises(ProjectNotFoundError):
            await self.service.update(
                self.project.id, {"description": "must not apply"}, self.owner_id
            )
        self.assertEqual(self.uow.rollback_count, 1)
        self.assertEqual(len(self.cache.rotated), rotations_before)

    async def test_list_is_visible_to_viewer_and_hides_missing_or_outsider_workspace(self) -> None:
        page, total = await self.service.list(
            workspace_id=self.workspace.id, user_id=self.viewer_id, limit=1
        )
        self.assertEqual(([project.id for project in page], total), ([self.project.id], 1))
        with self.assertRaises(ProjectNotFoundError):
            await self.service.list(
                workspace_id=self.workspace.id, user_id=self.outsider_id
            )
        with self.assertRaises(ProjectNotFoundError):
            await self.service.list(workspace_id=uuid4(), user_id=self.owner_id)

    async def test_failed_authorization_rolls_back_without_cache_rotation(self) -> None:
        with self.assertRaises(PermissionDeniedError):
            await self.service.delete(self.project.id, self.viewer_id)
        self.assertEqual(self.uow.rollback_count, 1)
        self.assertEqual(self.cache.rotated, [])

    async def test_project_cache_rotates_only_after_successful_commit(self) -> None:
        self.uow.commit_error = RuntimeError("commit failed")
        with self.assertRaisesRegex(RuntimeError, "commit failed"):
            await self.service.update(
                self.project.id, {"name": "No commit"}, self.owner_id
            )
        self.assertEqual(self.uow.rollback_count, 1)
        self.assertEqual(self.cache.rotated, [])

        self.uow.commit_error = None
        self.uow.projects.update_error = RuntimeError("database write failed")
        with self.assertRaisesRegex(RuntimeError, "database write failed"):
            await self.service.update(
                self.project.id, {"name": "Not persisted"}, self.owner_id
            )
        self.assertEqual(self.uow.rollback_count, 2)
        self.assertEqual(self.cache.rotated, [])

        self.uow.projects.update_error = None
        self.cache.rotate_error = OSError("cache unavailable")
        updated = await self.service.update(
            self.project.id, {"name": "Committed"}, self.owner_id
        )
        self.assertEqual(updated.name, "Committed")
        self.assertEqual(self.uow.commit_count, 2)
        self.assertEqual(self.uow.rollback_count, 2)

        await self.service.delete(self.project.id, self.owner_id)
        self.assertNotIn(self.project.id, self.uow.projects.items)
        self.assertEqual(self.uow.commit_count, 3)
        self.assertEqual(self.uow.rollback_count, 2)
