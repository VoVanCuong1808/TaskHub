"""Application boundary for project persistence and transactions."""

from typing import Protocol
from uuid import UUID

from app.models.entities import Project
from app.models.enums import ProjectStatus
from app.services.workspace_uow import WorkspaceStore


class ProjectStore(Protocol):
    async def add(self, project: Project) -> Project: ...

    async def get(self, project_id: UUID) -> Project | None: ...

    async def get_for_share(self, project_id: UUID) -> Project | None: ...

    async def get_for_update(self, project_id: UUID) -> Project | None: ...

    async def list(
        self, workspace_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Project], int]: ...

    async def update(
        self,
        project: Project,
        *,
        name: str,
        description: str | None,
        status: ProjectStatus,
    ) -> Project: ...

    async def delete(self, project: Project) -> None: ...


class ProjectUnitOfWork(Protocol):
    projects: ProjectStore
    workspaces: WorkspaceStore

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...
