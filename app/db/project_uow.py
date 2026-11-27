"""SQLAlchemy adapter for project request-scoped transactions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.project_repository import ProjectRepository
from app.repositories.workspace_repository import WorkspaceRepository
from app.services.project_uow import ProjectStore
from app.services.workspace_uow import WorkspaceStore


class SQLAlchemyProjectUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.projects: ProjectStore = ProjectRepository(session)
        self.workspaces: WorkspaceStore = WorkspaceRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
