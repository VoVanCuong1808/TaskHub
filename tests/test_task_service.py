"""Focused tests for the Day 5 task-management seam."""

from __future__ import annotations

import subprocess
import sys
import unittest
from copy import copy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.tasks import router as task_router
from app.core.deps import get_current_user, get_task_service
from app.core.exceptions import (
    CommentAuthorError,
    InvalidAssigneeError,
    LabelProjectMismatchError,
    PermissionDeniedError,
    ProjectArchivedError,
    TaskLabelNotFoundError,
    TaskNotFoundError,
)
from app.models.entities import (
    Comment,
    Label,
    Project,
    User,
    Workspace,
    WorkspaceMember,
)
from app.models.enums import (
    ProjectStatus,
    TaskPriority,
    TaskStatus,
    UserRole,
    WorkspaceRole,
)
from app.models.task import Task
from app.schemas.comment import CommentCreate, CommentUpdate
from app.schemas.label import LabelCreate, LabelUpdate
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.task_service import TaskService


class FakeTaskStore:
    def __init__(self, events: list[str]) -> None:
        self.items: dict[UUID, Task] = {}
        self.events = events
        self.locked_override: Task | None = None
        self.add_error: Exception | None = None
        self.return_missing_on_save = False

    async def add(self, task: Task) -> Task:
        self.events.append("add_task")
        if self.add_error:
            raise self.add_error
        self.items[task.id] = task
        return task

    async def list(
        self,
        *,
        project_id: UUID,
        status: TaskStatus | None,
        priority: TaskPriority | None,
        assignee_id: UUID | None,
        offset: int,
        limit: int,
    ) -> tuple[list[Task], int]:
        self.events.append("list_tasks")
        items = [task for task in self.items.values() if task.project_id == project_id]
        if status is not None:
            items = [task for task in items if task.status is status]
        if priority is not None:
            items = [task for task in items if task.priority is priority]
        if assignee_id is not None:
            items = [task for task in items if task.assignee_id == assignee_id]
        return items[offset : offset + limit], len(items)

    async def get(self, task_id: UUID) -> Task | None:
        self.events.append("get_task")
        return self.items.get(task_id)

    async def get_for_update(self, task_id: UUID) -> Task | None:
        self.events.append("lock_task")
        return self.locked_override or self.items.get(task_id)

    async def save(self, task: Task) -> Task | None:
        self.events.append("save_task")
        if self.return_missing_on_save:
            return None
        if task.id not in self.items:
            return None
        self.items[task.id] = task
        return task

    async def delete(self, task_id: UUID) -> None:
        self.events.append("delete_task")
        self.items.pop(task_id, None)


class FakeProjectStore:
    def __init__(self, events: list[str]) -> None:
        self.items: dict[UUID, Project] = {}
        self.events = events

    async def get(self, project_id: UUID) -> Project | None:
        self.events.append("get_project")
        return self.items.get(project_id)

    async def get_for_update(self, project_id: UUID) -> Project | None:
        self.events.append("lock_project")
        return self.items.get(project_id)


class FakeWorkspaceStore:
    def __init__(self, events: list[str]) -> None:
        self.items: dict[UUID, Workspace] = {}
        self.members: dict[tuple[UUID, UUID], WorkspaceMember] = {}
        self.events = events

    async def get(self, workspace_id: UUID) -> Workspace | None:
        self.events.append("get_workspace")
        return self.items.get(workspace_id)

    async def get_for_update(self, workspace_id: UUID) -> Workspace | None:
        self.events.append("lock_workspace")
        return self.items.get(workspace_id)

    async def get_member(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None:
        self.events.append(f"get_member:{user_id}")
        return self.members.get((workspace_id, user_id))

    async def get_member_for_update(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None:
        self.events.append(f"lock_member:{user_id}")
        return self.members.get((workspace_id, user_id))


class FakeUserStore:
    def __init__(self, events: list[str]) -> None:
        self.items: dict[UUID, User] = {}
        self.events = events

    async def get_for_share(self, user_id: UUID) -> User | None:
        self.events.append(f"share_user:{user_id}")
        return self.items.get(user_id)


class FakeLabelStore:
    def __init__(self, events: list[str]) -> None:
        self.items: dict[UUID, Label] = {}
        self.links: set[tuple[UUID, UUID]] = set()
        self.events = events

    async def add(self, label: Label) -> Label:
        self.events.append("add_label")
        label.id = label.id or uuid4()
        label.created_at = label.created_at or datetime.now(UTC)
        label.updated_at = label.updated_at or label.created_at
        self.items[label.id] = label
        return label

    async def list(
        self, project_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Label], int]:
        self.events.append("list_labels")
        items = sorted(
            (label for label in self.items.values() if label.project_id == project_id),
            key=lambda label: (label.created_at, label.id),
        )
        return items[offset : offset + limit], len(items)

    async def list_for_task(
        self, task_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Label], int]:
        self.events.append("list_task_labels")
        items = [
            self.items[label_id]
            for linked_task, label_id in self.links
            if linked_task == task_id
        ]
        items.sort(key=lambda label: (label.created_at, label.id))
        return items[offset : offset + limit], len(items)

    async def get(self, label_id: UUID) -> Label | None:
        self.events.append("get_label")
        return self.items.get(label_id)

    async def get_for_update(self, label_id: UUID) -> Label | None:
        self.events.append("lock_label")
        return self.items.get(label_id)

    async def update(
        self, label: Label, *, name: str | None, color: str | None
    ) -> Label:
        self.events.append("update_label")
        if name is not None:
            label.name = name
        if color is not None:
            label.color = color
        return label

    async def delete(self, label: Label) -> None:
        self.events.append("delete_label")
        self.items.pop(label.id, None)
        self.links = {link for link in self.links if link[1] != label.id}

    async def attach(self, task_id: UUID, label_id: UUID) -> None:
        self.events.append("attach_label")
        self.links.add((task_id, label_id))

    async def detach(self, task_id: UUID, label_id: UUID) -> bool:
        self.events.append("detach_label")
        link = (task_id, label_id)
        if link not in self.links:
            return False
        self.links.remove(link)
        return True


class FakeCommentStore:
    def __init__(self, events: list[str]) -> None:
        self.items: dict[UUID, Comment] = {}
        self.events = events

    async def add(self, comment: Comment) -> Comment:
        self.events.append("add_comment")
        comment.id = comment.id or uuid4()
        comment.created_at = comment.created_at or datetime.now(UTC)
        comment.updated_at = comment.updated_at or comment.created_at
        self.items[comment.id] = comment
        return comment

    async def list_for_task(
        self, task_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Comment], int]:
        self.events.append("list_comments")
        items = sorted(
            (comment for comment in self.items.values() if comment.task_id == task_id),
            key=lambda comment: (comment.created_at, comment.id),
        )
        return items[offset : offset + limit], len(items)

    async def get(self, comment_id: UUID) -> Comment | None:
        self.events.append("get_comment")
        return self.items.get(comment_id)

    async def get_for_update(self, comment_id: UUID) -> Comment | None:
        self.events.append("lock_comment")
        return self.items.get(comment_id)

    async def update(self, comment: Comment, content: str) -> Comment:
        self.events.append("update_comment")
        comment.content = content
        return comment

    async def delete(self, comment: Comment) -> None:
        self.events.append("delete_comment")
        self.items.pop(comment.id, None)


class FakeTaskUnitOfWork:
    def __init__(self) -> None:
        self.events: list[str] = []
        self.tasks = FakeTaskStore(self.events)
        self.projects = FakeProjectStore(self.events)
        self.workspaces = FakeWorkspaceStore(self.events)
        self.users = FakeUserStore(self.events)
        self.labels = FakeLabelStore(self.events)
        self.comments = FakeCommentStore(self.events)
        self.commit_count = 0
        self.rollback_count = 0

    async def commit(self) -> None:
        self.events.append("commit")
        self.commit_count += 1

    async def rollback(self) -> None:
        self.events.append("rollback")
        self.rollback_count += 1


def make_user(
    name: str,
    *,
    active: bool = True,
    role: UserRole = UserRole.MEMBER,
) -> User:
    return User(
        id=uuid4(),
        email=f"{name}-{uuid4().hex}@example.test",
        full_name=name,
        hashed_password="unused",
        is_active=active,
        role=role,
    )


class TaskSchemaTests(unittest.TestCase):
    def test_create_defaults_and_update_null_omission_contract(self) -> None:
        created = TaskCreate(project_id=uuid4(), title="Task")
        self.assertEqual(created.priority, TaskPriority.MEDIUM)
        self.assertIsNone(created.due_date)
        self.assertIsNone(created.assignee_id)

        omitted = TaskUpdate()
        self.assertEqual(omitted.model_dump(exclude_unset=True), {})
        cleared = TaskUpdate(due_date=None, assignee_id=None)
        self.assertEqual(
            cleared.model_dump(exclude_unset=True),
            {"due_date": None, "assignee_id": None},
        )
        for payload in (
            {"title": None},
            {"status": None},
            {"priority": None},
        ):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                TaskUpdate.model_validate(payload)
        for field in ("name", "color"):
            with self.subTest(field=field), self.assertRaises(ValidationError):
                LabelUpdate.model_validate({field: None})
        self.assertEqual(TaskUpdate().model_dump(exclude_unset=True), {})
        self.assertEqual(LabelUpdate().model_dump(exclude_unset=True), {})
        for schema, payload in (
            (TaskCreate, {"project_id": uuid4(), "title": "x", "priority": None}),
            (TaskUpdate, {"priority": None}),
        ):
            with self.subTest(schema=schema.__name__), self.assertRaises(
                ValidationError
            ):
                schema.model_validate(payload)

    def test_priority_enum_and_due_date_timezone_contract(self) -> None:
        with self.assertRaises(ValidationError):
            TaskUpdate(priority="critical")
        with self.assertRaises(ValidationError):
            TaskUpdate(due_date="2026-11-13T10:00:00")

        value = TaskUpdate(due_date="2026-11-13T10:00:00+07:00").due_date
        self.assertEqual(value, datetime(2026, 11, 13, 3, tzinfo=UTC))

    def test_label_and_comment_validation_contracts(self) -> None:
        label = LabelCreate(
            project_id=uuid4(), name="  Backlog  ", color="  blue  "
        )
        self.assertEqual((label.name, label.color), ("Backlog", "blue"))
        self.assertEqual(
            LabelUpdate(project_id=uuid4(), name="Renamed").model_dump(
                exclude_unset=True
            ),
            {"name": "Renamed"},
        )
        for payload in ({"name": None}, {"color": None}, {"name": "\x00"}):
            with self.subTest(payload=payload), self.assertRaises(ValidationError):
                LabelUpdate.model_validate(payload)

        self.assertEqual(CommentCreate(content="  hello  ").content, "hello")
        for schema, payload in (
            (CommentCreate, {}),
            (CommentUpdate, {}),
            (CommentUpdate, {"content": "   "}),
            (CommentCreate, {"content": "bad\x00value"}),
            (CommentUpdate, {"content": None}),
        ):
            with self.subTest(schema=schema.__name__, payload=payload), self.assertRaises(
                ValidationError
            ):
                schema.model_validate(payload)


class TaskServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.owner = make_user("owner")
        self.editor = make_user("editor")
        self.viewer = make_user("viewer")
        self.stale_owner = make_user("stale-owner")
        self.inactive = make_user("inactive", active=False)
        self.outsider = make_user("outsider")
        self.admin = make_user("admin", role=UserRole.ADMIN)
        self.workspace = Workspace(
            id=uuid4(), name="Workspace", owner_id=self.owner.id
        )
        self.project = Project(
            id=uuid4(),
            workspace_id=self.workspace.id,
            name="Project",
            status=ProjectStatus.ACTIVE,
        )
        self.uow = FakeTaskUnitOfWork()
        self.uow.workspaces.items[self.workspace.id] = self.workspace
        self.uow.projects.items[self.project.id] = self.project
        for user in (
            self.owner,
            self.editor,
            self.viewer,
            self.stale_owner,
            self.inactive,
            self.outsider,
            self.admin,
        ):
            self.uow.users.items[user.id] = user
        for user, role in (
            (self.editor, WorkspaceRole.EDITOR),
            (self.viewer, WorkspaceRole.VIEWER),
            (self.stale_owner, WorkspaceRole.OWNER),
            (self.inactive, WorkspaceRole.VIEWER),
        ):
            self.uow.workspaces.members[(self.workspace.id, user.id)] = (
                WorkspaceMember(
                    workspace_id=self.workspace.id, user_id=user.id, role=role
                )
            )
        self.service = TaskService(self.uow)

    async def _create(self, assignee_id: UUID | None = None) -> Task:
        return await self.service.create(
            project_id=self.project.id,
            user_id=self.owner.id,
            title="Task",
            assignee_id=assignee_id,
        )

    async def test_assignment_accepts_owner_members_and_stale_owner_viewer(self) -> None:
        for assignee in (
            self.owner,
            self.editor,
            self.viewer,
            self.stale_owner,
        ):
            with self.subTest(assignee=assignee.full_name):
                task = await self._create(assignee.id)
                self.assertEqual(task.assignee_id, assignee.id)
        self.assertEqual(self.uow.commit_count, 4)
        self.assertEqual(self.uow.rollback_count, 0)

    async def test_assignment_rejects_inactive_outsider_admin_and_unknown(self) -> None:
        for assignee_id in (
            self.inactive.id,
            self.outsider.id,
            self.admin.id,
            uuid4(),
        ):
            with self.subTest(assignee_id=assignee_id), self.assertRaises(
                InvalidAssigneeError
            ):
                await self._create(assignee_id)
        self.assertEqual(self.uow.commit_count, 0)
        self.assertEqual(self.uow.rollback_count, 4)

    async def test_service_owns_transaction_and_documented_lock_order(self) -> None:
        await self._create(self.editor.id)

        expected = [
            "lock_workspace",
            f"lock_member:{self.owner.id}",
            "lock_project",
            f"lock_member:{self.editor.id}",
            f"share_user:{self.editor.id}",
            "add_task",
            "commit",
        ]
        positions = [self.uow.events.index(event) for event in expected]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(self.uow.commit_count, 1)
        self.assertEqual(self.uow.rollback_count, 0)

        self.uow.events.clear()
        await self.service.list(project_id=self.project.id, user_id=self.owner.id)
        self.assertEqual(self.uow.commit_count, 1)
        self.assertNotIn("commit", self.uow.events)

    async def test_application_and_unexpected_errors_roll_back(self) -> None:
        with self.assertRaises(PermissionDeniedError):
            await self.service.create(
                project_id=self.project.id,
                user_id=self.viewer.id,
                title="Denied",
            )
        self.assertEqual(self.uow.rollback_count, 1)

        self.uow.tasks.add_error = RuntimeError("storage failed")
        with self.assertLogs("taskhub", level="ERROR"), self.assertRaisesRegex(
            RuntimeError, "storage failed"
        ):
            await self._create()
        self.assertEqual(self.uow.commit_count, 0)
        self.assertEqual(self.uow.rollback_count, 2)

    async def test_partial_update_uses_locked_fresh_task(self) -> None:
        original = await self._create()
        concurrent = copy(original)
        concurrent.title = "concurrent title"
        self.uow.tasks.locked_override = concurrent

        updated = await self.service.update(
            original.id, {"description": "mine"}, self.owner.id
        )

        self.assertEqual(updated.title, "concurrent title")
        self.assertEqual(updated.description, "mine")
        self.assertLess(
            self.uow.events.index("lock_project"),
            self.uow.events.index("lock_task"),
        )

    async def test_update_whitelists_fields_and_missing_save_is_not_success(self) -> None:
        task = await self._create()
        with self.assertRaises(ValueError):
            await self.service.update(task.id, {"created_by": self.viewer.id}, self.owner.id)

        self.uow.tasks.return_missing_on_save = True
        with self.assertRaises(TaskNotFoundError):
            await self.service.update(
                task.id, {"title": "no row"}, self.owner.id
            )

    async def test_label_update_whitelists_mutable_fields(self) -> None:
        label = await self.service.create_label(
            project_id=self.project.id,
            user_id=self.owner.id,
            name="Label",
            color="blue",
        )
        with self.assertRaises(ValueError):
            await self.service.update_label(
                label.id, {"project_id": uuid4()}, self.owner.id
            )
        self.assertEqual(label.project_id, self.project.id)

    def _stored_task(self, *, project: Project | None = None) -> Task:
        project = project or self.project
        task = Task(
            project_id=project.id,
            created_by=self.owner.id,
            title="Parent task",
        )
        self.uow.tasks.items[task.id] = task
        return task

    async def test_label_crud_role_matrix_pagination_and_immutable_project(self) -> None:
        first = await self.service.create_label(
            project_id=self.project.id,
            user_id=self.editor.id,
            name="First",
            color="blue",
        )
        second = await self.service.create_label(
            project_id=self.project.id,
            user_id=self.owner.id,
            name="Second",
            color="green",
        )
        first.created_at = datetime.now(UTC) - timedelta(seconds=1)
        second.created_at = datetime.now(UTC)
        labels, total = await self.service.list_labels(
            project_id=self.project.id,
            user_id=self.viewer.id,
            offset=1,
            limit=1,
        )
        self.assertEqual(total, 2)
        self.assertEqual([label.id for label in labels], [second.id])
        self.assertEqual(self.uow.commit_count, 2)

        updated = await self.service.update_label(
            first.id, {"name": "Renamed"}, self.owner.id
        )
        self.assertEqual(updated.name, "Renamed")
        self.assertEqual(updated.project_id, self.project.id)
        with self.assertRaises(PermissionDeniedError):
            await self.service.create_label(
                project_id=self.project.id,
                user_id=self.viewer.id,
                name="Denied",
                color="red",
            )

    async def test_label_attach_is_idempotent_and_detach_requires_link(self) -> None:
        task = self._stored_task()
        label = await self.service.create_label(
            project_id=self.project.id,
            user_id=self.owner.id,
            name="Attached",
            color="blue",
        )
        await self.service.attach_label(task.id, label.id, self.owner.id)
        await self.service.attach_label(task.id, label.id, self.owner.id)
        self.assertEqual(self.uow.labels.links, {(task.id, label.id)})

        labels, total = await self.service.list_task_labels(
            task.id, self.viewer.id
        )
        self.assertEqual((labels, total), ([label], 1))
        await self.service.detach_label(task.id, label.id, self.owner.id)
        with self.assertRaises(TaskLabelNotFoundError):
            await self.service.detach_label(task.id, label.id, self.owner.id)

    async def test_cross_project_label_and_archived_label_write_rules(self) -> None:
        sibling = Project(
            id=uuid4(), workspace_id=self.workspace.id, name="Sibling"
        )
        self.uow.projects.items[sibling.id] = sibling
        task = self._stored_task()
        label = await self.service.create_label(
            project_id=sibling.id,
            user_id=self.owner.id,
            name="Sibling",
            color="orange",
        )
        with self.assertRaises(LabelProjectMismatchError):
            await self.service.attach_label(task.id, label.id, self.owner.id)

        with self.assertRaises(Exception) as caught:
            await self.service.attach_label(task.id, uuid4(), self.viewer.id)
        self.assertEqual(getattr(caught.exception, "status_code", None), 404)

        with self.assertRaises(PermissionDeniedError):
            await self.service.attach_label(task.id, label.id, self.viewer.id)

        self.project.status = ProjectStatus.ARCHIVED
        with self.assertRaises(ProjectArchivedError):
            await self.service.create_label(
                project_id=self.project.id,
                user_id=self.owner.id,
                name="Archived",
                color="gray",
            )

    async def test_comment_author_role_archived_ordering_and_pagination(self) -> None:
        task = self._stored_task()
        first = await self.service.create_comment(
            task.id, self.editor.id, "first"
        )
        second = await self.service.create_comment(
            task.id, self.owner.id, "second"
        )
        first.created_at = datetime.now(UTC) - timedelta(seconds=1)
        second.created_at = datetime.now(UTC)
        comments, total = await self.service.list_comments(
            task.id, self.viewer.id, offset=1, limit=1
        )
        self.assertEqual(total, 2)
        self.assertEqual([comment.id for comment in comments], [second.id])
        self.assertEqual(first.author_id, self.editor.id)

        with self.assertRaises(CommentAuthorError):
            await self.service.update_comment(first.id, self.owner.id, "owner edit")
        self.uow.events.clear()
        updated = await self.service.update_comment(
            first.id, self.editor.id, "author edit"
        )
        self.assertEqual(updated.content, "author edit")
        self.assertLess(
            self.uow.events.index("lock_workspace"),
            self.uow.events.index("lock_project"),
        )
        self.assertLess(
            self.uow.events.index("lock_project"),
            self.uow.events.index("lock_task"),
        )
        self.assertLess(
            self.uow.events.index("lock_task"),
            self.uow.events.index("lock_comment"),
        )

        self.uow.workspaces.members[(self.workspace.id, self.editor.id)].role = (
            WorkspaceRole.VIEWER
        )
        with self.assertRaises(PermissionDeniedError):
            await self.service.delete_comment(first.id, self.editor.id)

        self.project.status = ProjectStatus.ARCHIVED
        with self.assertRaises(ProjectArchivedError):
            await self.service.create_comment(task.id, self.owner.id, "archived")
        self.assertEqual(
            (await self.service.get_comment(second.id, self.viewer.id)).id,
            second.id,
        )


class TaskQueryContractTests(unittest.TestCase):
    def test_shared_pagination_and_task_filters_are_query_parameters(self) -> None:
        user = make_user("query-user")

        class ListService:
            def __init__(self) -> None:
                self.kwargs: dict[str, object] = {}
                self.calls: list[dict[str, object]] = []

            async def list(self, **kwargs):
                self.kwargs = kwargs
                self.calls.append(kwargs)
                return [], 0

        service = ListService()
        app = FastAPI()
        app.include_router(task_router)
        app.include_router(task_router, prefix="/api/v1")
        app.dependency_overrides[get_task_service] = lambda: service
        app.dependency_overrides[get_current_user] = lambda: user
        project_id = uuid4()

        with TestClient(app) as client:
            response = client.get(
                "/tasks",
                params={
                    "project_id": str(project_id),
                    "status": "done",
                    "priority": "high",
                    "assignee_id": str(uuid4()),
                    "page": 2,
                    "limit": 3,
                },
            )
            page_two = client.get(
                "/api/v1/tasks",
                params={
                    "project_id": str(project_id),
                    "page": 2,
                    "limit": 3,
                },
            )
            default_page = client.get(
                "/api/v1/tasks", params={"project_id": str(project_id)}
            )
            obsolete_offset = client.get(
                "/tasks",
                params={
                    "project_id": str(project_id),
                    "page": 1,
                    "offset": 0,
                },
            )
            invalid = [
                client.get(
                    "/tasks",
                    params={"project_id": str(project_id), "page": 0},
                ),
                client.get(
                    "/tasks",
                    params={"project_id": str(project_id), "priority": "critical"},
                ),
                client.get(
                    "/tasks",
                    params={"project_id": str(project_id), "assignee_id": "bad"},
                ),
                client.get(
                    "/tasks",
                    params={
                        "project_id": str(project_id),
                        "page": 9_223_372_036_854_775_808,
                    },
                ),
            ]
            schema = client.get("/openapi.json").json()

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"items": [], "total": 0})
        self.assertEqual(service.calls[0]["project_id"], project_id)
        self.assertEqual(service.calls[0]["status"], TaskStatus.DONE)
        self.assertEqual(service.calls[0]["priority"], TaskPriority.HIGH)
        self.assertIsInstance(service.calls[0]["assignee_id"], UUID)
        self.assertEqual(service.calls[0]["offset"], 3)
        self.assertEqual(service.calls[0]["limit"], 3)
        self.assertEqual(page_two.status_code, 200, page_two.text)
        self.assertEqual(service.calls[1]["offset"], 3)
        self.assertEqual(default_page.status_code, 200, default_page.text)
        self.assertEqual(service.calls[2]["offset"], 0)
        self.assertEqual(service.calls[2]["limit"], 20)
        self.assertEqual(obsolete_offset.status_code, 422)
        self.assertTrue(all(response.status_code == 422 for response in invalid))
        task_list_parameters = {
            parameter["name"]
            for parameter in schema["paths"]["/api/v1/tasks"]["get"]["parameters"]
        }
        self.assertTrue(
            {"project_id", "status", "priority", "assignee_id", "page", "limit"}
            <= task_list_parameters
        )
        self.assertNotIn("offset", task_list_parameters)


class TaskArchitectureTests(unittest.TestCase):
    def test_policies_stay_framework_free_and_task_repository_has_no_transactions(self) -> None:
        root = Path(__file__).resolve().parents[1]
        policy_script = """
import inspect
import sys
import app.services.task_authorization as policy
assert 'fastapi' not in sys.modules
assert 'sqlalchemy' not in inspect.getsource(policy)
"""
        repository_script = """
from app.repositories.task_database import TaskRepository
assert not hasattr(TaskRepository, 'commit')
assert not hasattr(TaskRepository, 'rollback')
"""
        for script in (policy_script, repository_script):
            subprocess.run([sys.executable, "-c", script], cwd=root, check=True)
