"""SQLAlchemy adapter for request-scoped task-management transactions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.comment_database import CommentRepository
from app.repositories.label_database import LabelRepository
from app.repositories.task_database import (
    TaskProjectRepository,
    TaskRepository,
    TaskUserRepository,
    TaskWorkspaceRepository,
)


class SQLAlchemyTaskManagementUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.tasks = TaskRepository(session)
        self.projects = TaskProjectRepository(session)
        self.workspaces = TaskWorkspaceRepository(session)
        self.users = TaskUserRepository(session)
        self.labels = LabelRepository(session)
        self.comments = CommentRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
