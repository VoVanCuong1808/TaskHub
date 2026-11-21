"""SQLAlchemy adapter for request-scoped task-management transactions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.comment_database import CommentRepository
from app.repositories.label_database import LabelRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.task_database import (
    TaskRepository,
    TaskUserRepository,
    TaskWorkspaceRepository,
)
from app.services.project_uow import ProjectStore
from app.services.task_uow import (
    CommentStore,
    LabelStore,
    TaskStore,
    TaskUserStore,
    TaskWorkspaceStore,
)


class SQLAlchemyTaskManagementUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.tasks: TaskStore = TaskRepository(session)
        self.projects: ProjectStore = ProjectRepository(session)
        self.workspaces: TaskWorkspaceStore = TaskWorkspaceRepository(session)
        self.users: TaskUserStore = TaskUserRepository(session)
        self.labels: LabelStore = LabelRepository(session)
        self.comments: CommentStore = CommentRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
