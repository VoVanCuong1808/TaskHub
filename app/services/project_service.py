"""Project use cases, workspace authorization and transaction boundaries."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from typing import cast
from uuid import UUID

from app.core.constants import DEFAULT_PAGE_LIMIT
from app.core.exceptions import (
    ApplicationError,
    ProjectNotFoundError,
    WorkspaceNotFoundError,
)
from app.models.entities import Project
from app.models.enums import ProjectStatus, WorkspacePermission
from app.services.project_uow import ProjectUnitOfWork
from app.services.task_list_cache import TaskListCache
from app.services.workspace_authorization import (
    WorkspaceAuthorizationContext,
    authorize_workspace_access,
)

PROJECT_UPDATE_FIELDS = frozenset({"name", "description", "status"})
logger = logging.getLogger("taskhub")


class ProjectService:
    def __init__(
        self, uow: ProjectUnitOfWork, cache: TaskListCache | None = None
    ) -> None:
        self._uow = uow
        self._cache = cache

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        try:
            yield
            await self._uow.commit()
        except ApplicationError:
            await self._uow.rollback()
            raise
        except BaseException:
            logger.exception("Project transaction failed; rolling back")
            await self._uow.rollback()
            raise

    async def _authorize_workspace(
        self,
        workspace_id: UUID,
        user_id: UUID,
        permission: WorkspacePermission,
        *,
        write: bool,
    ) -> None:
        context = await self._workspace_context(workspace_id, user_id, write=write)
        try:
            authorize_workspace_access(context, user_id, permission)
        except WorkspaceNotFoundError:
            raise ProjectNotFoundError() from None

    async def _workspace_context(
        self, workspace_id: UUID, user_id: UUID, *, write: bool
    ) -> WorkspaceAuthorizationContext:
        workspaces = self._uow.workspaces
        workspace = await (
            workspaces.get_for_share(workspace_id)
            if write
            else workspaces.get(workspace_id)
        )
        if workspace is None:
            raise ProjectNotFoundError()
        member = await (
            workspaces.get_member_for_share(workspace_id, user_id)
            if write
            else workspaces.get_member(workspace_id, user_id)
        )
        return WorkspaceAuthorizationContext(
            workspace.owner_id, member.role if member else None
        )

    async def _project(
        self,
        project_id: UUID,
        user_id: UUID,
        permission: WorkspacePermission,
        *,
        write: bool,
    ) -> Project:
        project = await self._uow.projects.get(project_id)
        if project is None:
            raise ProjectNotFoundError()
        workspace_id = project.workspace_id
        context = await self._workspace_context(workspace_id, user_id, write=write)
        if write:
            project = await self._uow.projects.get_for_update(project_id)
            if project is None or project.workspace_id != workspace_id:
                raise ProjectNotFoundError()
        try:
            authorize_workspace_access(context, user_id, permission)
        except WorkspaceNotFoundError:
            raise ProjectNotFoundError() from None
        return project

    async def create(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        name: str,
        description: str | None = None,
        status: ProjectStatus = ProjectStatus.ACTIVE,
    ) -> Project:
        async with self._transaction():
            await self._authorize_workspace(
                workspace_id, user_id, WorkspacePermission.PROJECT_CREATE, write=True
            )
            project = await self._uow.projects.add(
                Project(
                    workspace_id=workspace_id,
                    name=name,
                    description=description,
                    status=status,
                )
            )
        return project

    async def list(
        self,
        *,
        workspace_id: UUID,
        user_id: UUID,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[Project], int]:
        await self._authorize_workspace(
            workspace_id, user_id, WorkspacePermission.PROJECT_READ, write=False
        )
        return await self._uow.projects.list(
            workspace_id, offset=offset, limit=limit
        )

    async def get(self, project_id: UUID, user_id: UUID) -> Project:
        return await self._project(
            project_id, user_id, WorkspacePermission.PROJECT_READ, write=False
        )

    async def update(
        self, project_id: UUID, changes: Mapping[str, object], user_id: UUID
    ) -> Project:
        if changes.keys() - PROJECT_UPDATE_FIELDS:
            raise ValueError("Unsupported project fields")
        async with self._transaction():
            project = await self._project(
                project_id, user_id, WorkspacePermission.PROJECT_UPDATE, write=True
            )
            if changes:
                project = await self._uow.projects.update(
                    project,
                    name=cast(str, changes.get("name", project.name)),
                    description=cast(
                        str | None, changes.get("description", project.description)
                    ),
                    status=cast(ProjectStatus, changes.get("status", project.status)),
                )
        if changes:
            await self._rotate_task_cache(project.id)
        return project

    async def delete(self, project_id: UUID, user_id: UUID) -> None:
        async with self._transaction():
            project = await self._project(
                project_id, user_id, WorkspacePermission.PROJECT_DELETE, write=True
            )
            await self._uow.projects.delete(project)
        await self._rotate_task_cache(project.id)

    async def _rotate_task_cache(self, project_id: UUID) -> None:
        if self._cache is None:
            return
        try:
            await self._cache.rotate(project_id)
        except Exception:
            logger.warning(
                "Task-list cache invalidation failed after project commit",
                exc_info=True,
            )
