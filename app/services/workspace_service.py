"""Workspace management use cases."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from app.models.entities import User, Workspace, WorkspaceMember
from app.models.enums import WorkspacePermission, WorkspaceRole
from app.repositories.workspace_repository import WorkspaceRepository

logger = logging.getLogger("taskhub")


class WorkspaceService:
    def __init__(self, repository: WorkspaceRepository) -> None:
        self._repository = repository

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        try:
            yield
            await self._repository.commit()
        except BaseException:
            logger.warning("Workspace transaction failed; rolling back")
            await self._repository.rollback()
            raise

    async def create(self, name: str, owner: User) -> Workspace:
        async with self._transaction():
            workspace = await self._repository.add(
                Workspace(name=name, owner_id=owner.id), owner
            )
        return workspace

    async def list(self, user_id: UUID) -> list[Workspace]:
        return await self._repository.list_visible(user_id)

    async def get(self, workspace_id: UUID, user_id: UUID) -> Workspace:
        return await self._repository.authorize(
            workspace_id, user_id, WorkspacePermission.WORKSPACE_READ
        )

    async def update(
        self, workspace_id: UUID, user_id: UUID, name: str
    ) -> Workspace:
        async with self._transaction():
            workspace = await self._repository.authorize(
                workspace_id, user_id, WorkspacePermission.WORKSPACE_UPDATE
            )
            workspace.name = name
        return workspace

    async def delete(self, workspace_id: UUID, user_id: UUID) -> None:
        async with self._transaction():
            workspace = await self._repository.authorize(
                workspace_id, user_id, WorkspacePermission.WORKSPACE_DELETE
            )
            await self._repository.delete(workspace)

    async def list_members(
        self, workspace_id: UUID, user_id: UUID
    ) -> list[WorkspaceMember]:
        return await self._repository.list_members(workspace_id, user_id)

    async def add_member(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        email: str,
        role: WorkspaceRole,
    ) -> WorkspaceMember:
        async with self._transaction():
            member = await self._repository.add_member(
                workspace_id, actor_id, email.lower(), role
            )
        return member

    async def update_member(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        user_id: UUID,
        role: WorkspaceRole,
    ) -> WorkspaceMember:
        async with self._transaction():
            member = await self._repository.update_member(
                workspace_id, actor_id, user_id, role
            )
        return member

    async def remove_member(
        self, workspace_id: UUID, actor_id: UUID, user_id: UUID
    ) -> None:
        async with self._transaction():
            await self._repository.remove_member(workspace_id, actor_id, user_id)
