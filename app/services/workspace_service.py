"""Workspace use cases and transaction boundary."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.core.constants import (
    DEFAULT_PAGE_LIMIT,
    WORKSPACE_ALREADY_MEMBER_MESSAGE,
    WORKSPACE_OWNER_ALREADY_MEMBER_MESSAGE,
    WORKSPACE_OWNER_REMOVE_MESSAGE,
    WORKSPACE_OWNER_ROLE_CHANGE_MESSAGE,
    WORKSPACE_OWNER_ROLE_RESERVED_MESSAGE,
)
from app.core.exceptions import (
    ApplicationError,
    WorkspaceConflictError,
    WorkspaceMemberNotFoundError,
    WorkspaceNotFoundError,
)
from app.models.entities import Workspace, WorkspaceMember
from app.models.enums import WorkspacePermission, WorkspaceRole
from app.services.workspace_authorization import (
    WorkspaceAuthorizationContext,
    authorize_workspace_access,
)
from app.services.workspace_uow import WorkspaceUnitOfWork

logger = logging.getLogger("taskhub")


class WorkspaceService:
    def __init__(self, uow: WorkspaceUnitOfWork) -> None:
        self._uow = uow

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        try:
            yield
            await self._uow.commit()
        except ApplicationError:
            await self._uow.rollback()
            raise
        except Exception:
            logger.exception("Workspace transaction failed; rolling back")
            await self._uow.rollback()
            raise

    async def _authorize(
        self,
        workspace_id: UUID,
        user_id: UUID,
        permission: WorkspacePermission,
        *,
        write: bool = False,
    ) -> tuple[Workspace, WorkspaceMember | None]:
        workspaces = self._uow.workspaces
        workspace = await (
            workspaces.get_for_update(workspace_id)
            if write
            else workspaces.get(workspace_id)
        )
        if workspace is None:
            raise WorkspaceNotFoundError()

        member = await (
            workspaces.get_member_for_update(workspace_id, user_id)
            if write
            else workspaces.get_member(workspace_id, user_id)
        )
        authorize_workspace_access(
            WorkspaceAuthorizationContext(
                workspace.owner_id, member.role if member else None
            ),
            user_id,
            permission,
        )
        return workspace, member

    async def create(self, name: str, owner_id: UUID) -> Workspace:
        async with self._transaction():
            workspace = await self._uow.workspaces.add(
                Workspace(name=name, owner_id=owner_id)
            )
            await self._uow.workspaces.add_member(
                WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=owner_id,
                    role=WorkspaceRole.OWNER,
                )
            )
        return workspace

    async def list(
        self, user_id: UUID, *, offset: int = 0, limit: int = DEFAULT_PAGE_LIMIT
    ) -> tuple[list[Workspace], int]:
        return await self._uow.workspaces.list_visible(
            user_id, offset=offset, limit=limit
        )

    async def get(self, workspace_id: UUID, user_id: UUID) -> Workspace:
        workspace, _ = await self._authorize(
            workspace_id, user_id, WorkspacePermission.WORKSPACE_READ
        )
        return workspace

    async def update(
        self, workspace_id: UUID, user_id: UUID, name: str
    ) -> Workspace:
        async with self._transaction():
            workspace, _ = await self._authorize(
                workspace_id,
                user_id,
                WorkspacePermission.WORKSPACE_UPDATE,
                write=True,
            )
            return await self._uow.workspaces.update(workspace, name)

    async def delete(self, workspace_id: UUID, user_id: UUID) -> None:
        async with self._transaction():
            workspace, _ = await self._authorize(
                workspace_id,
                user_id,
                WorkspacePermission.WORKSPACE_DELETE,
                write=True,
            )
            await self._uow.workspaces.delete(workspace)

    async def list_members(
        self,
        workspace_id: UUID,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[WorkspaceMember], int]:
        await self._authorize(
            workspace_id, user_id, WorkspacePermission.MEMBER_READ
        )
        return await self._uow.workspaces.list_members(
            workspace_id, offset=offset, limit=limit
        )

    async def add_member(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        email: str,
        role: WorkspaceRole,
    ) -> WorkspaceMember:
        async with self._transaction():
            workspace, _ = await self._authorize(
                workspace_id,
                actor_id,
                WorkspacePermission.MEMBER_INVITE,
                write=True,
            )
            user = await self._uow.users.get_by_email(email.lower())
            if user is None or not user.is_active:
                raise WorkspaceMemberNotFoundError()
            if user.id == workspace.owner_id:
                raise WorkspaceConflictError(WORKSPACE_OWNER_ALREADY_MEMBER_MESSAGE)
            existing = await self._uow.workspaces.get_member_for_update(
                workspace_id, user.id
            )
            if existing is not None:
                raise WorkspaceConflictError(WORKSPACE_ALREADY_MEMBER_MESSAGE)
            if role is WorkspaceRole.OWNER:
                raise WorkspaceConflictError(WORKSPACE_OWNER_ROLE_RESERVED_MESSAGE)
            return await self._uow.workspaces.add_member(
                WorkspaceMember(
                    workspace_id=workspace_id,
                    user_id=user.id,
                    role=role,
                )
            )

    async def update_member(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        user_id: UUID,
        role: WorkspaceRole,
    ) -> WorkspaceMember:
        async with self._transaction():
            workspace, actor_member = await self._authorize(
                workspace_id,
                actor_id,
                WorkspacePermission.MEMBER_UPDATE,
                write=True,
            )
            member = (
                actor_member
                if user_id == actor_id
                else await self._uow.workspaces.get_member_for_update(
                    workspace_id, user_id
                )
            )
            if member is None:
                raise WorkspaceMemberNotFoundError()
            if user_id == workspace.owner_id:
                raise WorkspaceConflictError(WORKSPACE_OWNER_ROLE_CHANGE_MESSAGE)
            if role is WorkspaceRole.OWNER:
                raise WorkspaceConflictError(WORKSPACE_OWNER_ROLE_RESERVED_MESSAGE)
            return await self._uow.workspaces.update_member(member, role)

    async def remove_member(
        self, workspace_id: UUID, actor_id: UUID, user_id: UUID
    ) -> None:
        async with self._transaction():
            workspace, actor_member = await self._authorize(
                workspace_id,
                actor_id,
                WorkspacePermission.MEMBER_REMOVE,
                write=True,
            )
            member = (
                actor_member
                if user_id == actor_id
                else await self._uow.workspaces.get_member_for_update(
                    workspace_id, user_id
                )
            )
            if member is None:
                raise WorkspaceMemberNotFoundError()
            if user_id == workspace.owner_id:
                raise WorkspaceConflictError(WORKSPACE_OWNER_REMOVE_MESSAGE)
            await self._uow.workspaces.delete_member(member)
