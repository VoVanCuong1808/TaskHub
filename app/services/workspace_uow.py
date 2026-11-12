"""Application boundary for workspace persistence and transactions."""

from typing import Protocol
from uuid import UUID

from app.models.entities import User, Workspace, WorkspaceMember
from app.models.enums import WorkspaceRole


class WorkspaceStore(Protocol):
    async def add(self, workspace: Workspace) -> Workspace: ...

    async def add_member(self, member: WorkspaceMember) -> WorkspaceMember: ...

    async def update(
        self, workspace: Workspace, name: str
    ) -> Workspace: ...

    async def get(self, workspace_id: UUID) -> Workspace | None: ...

    async def get_for_update(self, workspace_id: UUID) -> Workspace | None: ...

    async def get_member(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None: ...

    async def get_member_for_update(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None: ...

    async def list_visible(
        self, user_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Workspace], int]: ...

    async def list_members(
        self, workspace_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[WorkspaceMember], int]: ...

    async def update_member(
        self, member: WorkspaceMember, role: WorkspaceRole
    ) -> WorkspaceMember: ...

    async def delete_member(self, member: WorkspaceMember) -> None: ...

    async def delete(self, workspace: Workspace) -> None: ...


class UserLookup(Protocol):
    async def get_by_email(self, email: str) -> User | None: ...


class WorkspaceUnitOfWork(Protocol):
    workspaces: WorkspaceStore
    users: UserLookup

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
