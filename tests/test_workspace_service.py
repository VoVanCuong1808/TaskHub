"""Workspace use-case tests using the service's UoW seam."""

import unittest
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.core.exceptions import (
    PermissionDeniedError,
    WorkspaceConflictError,
    WorkspaceMemberNotFoundError,
    WorkspaceNotFoundError,
)
from app.models.entities import User, Workspace, WorkspaceMember
from app.models.enums import WorkspaceRole
from app.schemas.workspace import WorkspaceMemberCreate, WorkspaceMemberUpdate
from app.services.workspace_service import WorkspaceService


class FakeWorkspaceStore:
    def __init__(self) -> None:
        self.items: dict[UUID, Workspace] = {}
        self.members: dict[tuple[UUID, UUID], WorkspaceMember] = {}
        self.events: list[str] = []

    async def add(self, workspace: Workspace) -> Workspace:
        self.events.append("add_workspace")
        if workspace.id is None:
            workspace.id = uuid4()
        self.items[workspace.id] = workspace
        return workspace

    async def add_member(self, member: WorkspaceMember) -> WorkspaceMember:
        self.events.append("add_member")
        self.members[(member.workspace_id, member.user_id)] = member
        return member

    async def get(self, workspace_id: UUID) -> Workspace | None:
        self.events.append("get_workspace")
        return self.items.get(workspace_id)

    async def get_for_update(self, workspace_id: UUID) -> Workspace | None:
        self.events.append("lock_workspace")
        return self.items.get(workspace_id)

    async def get_member(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None:
        self.events.append("get_member")
        return self.members.get((workspace_id, user_id))

    async def get_member_for_update(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None:
        self.events.append(f"lock_member:{user_id}")
        return self.members.get((workspace_id, user_id))

    async def list_visible(
        self, user_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Workspace], int]:
        visible = [
            workspace
            for workspace in self.items.values()
            if workspace.owner_id == user_id
            or (workspace.id, user_id) in self.members
        ]
        return visible[offset : offset + limit], len(visible)

    async def list_members(
        self, workspace_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[WorkspaceMember], int]:
        members = [
            member
            for (candidate, _), member in self.members.items()
            if candidate == workspace_id
        ]
        return members[offset : offset + limit], len(members)

    async def update(self, workspace: Workspace, name: str) -> Workspace:
        workspace.name = name
        return workspace

    async def update_member(
        self, member: WorkspaceMember, role: WorkspaceRole
    ) -> WorkspaceMember:
        member.role = role
        return member

    async def delete_member(self, member: WorkspaceMember) -> None:
        del self.members[(member.workspace_id, member.user_id)]

    async def delete(self, workspace: Workspace) -> None:
        del self.items[workspace.id]


class FakeUserLookup:
    def __init__(self, users: list[User]) -> None:
        self.users = {str(user.email).lower(): user for user in users}
        self.lookups: list[str] = []

    async def get_by_email(self, email: str) -> User | None:
        self.lookups.append(email)
        return self.users.get(email)


class FakeUnitOfWork:
    def __init__(self, users: list[User] | None = None) -> None:
        self.workspaces = FakeWorkspaceStore()
        self.users = FakeUserLookup(users or [])
        self.events = self.workspaces.events
        self.commit_count = 0
        self.rollback_count = 0
        self.commit_error: Exception | None = None

    async def commit(self) -> None:
        self.events.append("commit")
        self.commit_count += 1
        if self.commit_error:
            raise self.commit_error

    async def rollback(self) -> None:
        self.events.append("rollback")
        self.rollback_count += 1


class WorkspaceServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.owner = User(
            id=uuid4(),
            email="owner@example.test",
            full_name="Owner",
            hashed_password="unused",
            is_active=True,
        )
        self.viewer = User(
            id=uuid4(),
            email="viewer@example.test",
            full_name="Viewer",
            hashed_password="unused",
            is_active=True,
        )
        self.invitee = User(
            id=uuid4(),
            email="invitee@example.test",
            full_name="Invitee",
            hashed_password="unused",
            is_active=True,
        )
        self.workspace = Workspace(
            id=uuid4(), name="Workspace", owner_id=self.owner.id
        )
        self.uow = FakeUnitOfWork([self.owner, self.viewer, self.invitee])
        self.uow.workspaces.items[self.workspace.id] = self.workspace
        self.uow.workspaces.members[(self.workspace.id, self.owner.id)] = (
            WorkspaceMember(
                workspace_id=self.workspace.id,
                user_id=self.owner.id,
                role=WorkspaceRole.OWNER,
            )
        )
        self.uow.workspaces.members[(self.workspace.id, self.viewer.id)] = (
            WorkspaceMember(
                workspace_id=self.workspace.id,
                user_id=self.viewer.id,
                role=WorkspaceRole.VIEWER,
            )
        )
        self.service = WorkspaceService(self.uow)

    async def test_create_persists_workspace_and_owner_membership_in_one_uow(self) -> None:
        created = await self.service.create("New", self.invitee.id)

        self.assertEqual(created.owner_id, self.invitee.id)
        membership = self.uow.workspaces.members[(created.id, self.invitee.id)]
        self.assertEqual(membership.role, WorkspaceRole.OWNER)
        self.assertEqual(self.uow.commit_count, 1)
        self.assertEqual(self.uow.rollback_count, 0)
        self.assertEqual(
            self.uow.events,
            ["add_workspace", "add_member", "commit"],
        )

    async def test_invite_normalizes_email_and_keeps_domain_logic_in_service(self) -> None:
        member = await self.service.add_member(
            self.workspace.id,
            self.owner.id,
            "INVITEE@EXAMPLE.TEST",
            WorkspaceRole.EDITOR,
        )

        self.assertEqual(member.user_id, self.invitee.id)
        self.assertEqual(member.role, WorkspaceRole.EDITOR)
        self.assertEqual(self.uow.users.lookups, ["invitee@example.test"])
        self.assertEqual(self.uow.commit_count, 1)
        self.assertLess(
            self.uow.events.index("lock_workspace"),
            self.uow.events.index(f"lock_member:{self.owner.id}"),
        )
        self.assertLess(
            self.uow.events.index(f"lock_member:{self.owner.id}"),
            self.uow.events.index(f"lock_member:{self.invitee.id}"),
        )

    async def test_member_role_payloads_allow_only_editor_or_viewer(self) -> None:
        for schema in (WorkspaceMemberCreate, WorkspaceMemberUpdate):
            with self.subTest(schema=schema.__name__):
                email = {"email": "user@example.com"} if schema is WorkspaceMemberCreate else {}
                for role in ("editor", "viewer"):
                    payload = {"role": role, **email}
                    self.assertEqual(schema.model_validate(payload).role.value, role)
                with self.assertRaises(ValidationError):
                    schema.model_validate({"role": "owner", **email})
                self.assertEqual(
                    schema.model_json_schema()["properties"]["role"]["enum"],
                    ["editor", "viewer"],
                )

    async def test_hidden_and_forbidden_actor_checks_precede_user_lookup(self) -> None:
        with self.assertNoLogs("taskhub", level="WARNING"), self.assertRaises(
            WorkspaceNotFoundError
        ):
            await self.service.add_member(
                self.workspace.id,
                uuid4(),
                self.invitee.email,
                WorkspaceRole.VIEWER,
            )
        self.assertEqual(self.uow.users.lookups, [])
        self.assertEqual(self.uow.rollback_count, 1)

        self.uow.rollback_count = 0
        with self.assertNoLogs("taskhub", level="WARNING"), self.assertRaises(
            PermissionDeniedError
        ):
            await self.service.add_member(
                self.workspace.id,
                self.viewer.id,
                self.invitee.email,
                WorkspaceRole.VIEWER,
            )
        self.assertEqual(self.uow.users.lookups, [])
        self.assertEqual(self.uow.rollback_count, 1)

    async def test_unknown_inactive_duplicate_and_reserved_owner_rules(self) -> None:
        inactive = User(
            id=uuid4(),
            email="inactive@example.test",
            full_name="Inactive",
            hashed_password="unused",
            is_active=False,
        )
        self.uow.users.users[inactive.email] = inactive
        for email in ("missing@example.test", inactive.email):
            with self.subTest(email=email):
                with self.assertNoLogs(
                    "taskhub", level="WARNING"
                ), self.assertRaises(WorkspaceMemberNotFoundError):
                    await self.service.add_member(
                        self.workspace.id,
                        self.owner.id,
                        email,
                        WorkspaceRole.OWNER,
                    )
                self.assertEqual(self.uow.rollback_count, 1)
                self.uow.rollback_count = 0

        with self.assertRaises(WorkspaceConflictError):
            await self.service.add_member(
                self.workspace.id,
                self.owner.id,
                self.viewer.email,
                WorkspaceRole.EDITOR,
            )
        with self.assertRaises(WorkspaceConflictError):
            await self.service.add_member(
                self.workspace.id,
                self.owner.id,
                self.invitee.email,
                WorkspaceRole.OWNER,
            )
        self.assertEqual(self.uow.commit_count, 0)

    async def test_missing_member_precedes_reserved_owner_conflicts(self) -> None:
        missing_id = uuid4()
        with self.assertRaises(WorkspaceMemberNotFoundError):
            await self.service.update_member(
                self.workspace.id,
                self.owner.id,
                missing_id,
                WorkspaceRole.OWNER,
            )
        with self.assertRaises(WorkspaceConflictError):
            await self.service.update_member(
                self.workspace.id,
                self.owner.id,
                self.viewer.id,
                WorkspaceRole.OWNER,
            )
        with self.assertRaises(WorkspaceMemberNotFoundError):
            await self.service.remove_member(
                self.workspace.id, self.owner.id, missing_id
            )
        with self.assertRaises(WorkspaceConflictError):
            await self.service.remove_member(
                self.workspace.id, self.owner.id, self.owner.id
            )
        self.assertEqual(self.uow.commit_count, 0)

    async def test_unexpected_failure_logs_exception_and_rolls_back(self) -> None:
        self.uow.commit_error = RuntimeError("commit failed")

        with self.assertLogs("taskhub", level="ERROR") as captured, self.assertRaisesRegex(
            RuntimeError, "commit failed"
        ):
            await self.service.create("New", self.invitee.id)

        self.assertIn("Workspace transaction failed", captured.output[0])
        self.assertIn("RuntimeError: commit failed", captured.output[0])
        self.assertEqual(self.uow.commit_count, 1)
        self.assertEqual(self.uow.rollback_count, 1)
