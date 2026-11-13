"""SQLAlchemy adapter for workspace request-scoped transactions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.user_repository import UserRepository
from app.repositories.workspace_repository import WorkspaceRepository


class SQLAlchemyWorkspaceUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.workspaces = WorkspaceRepository(session)
        self.users = UserRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
