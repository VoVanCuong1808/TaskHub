"""SQL-only persistence store for task comments."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Comment


class CommentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, comment: Comment) -> Comment:
        self._session.add(comment)
        await self._session.flush()
        return comment

    async def list_for_task(
        self, task_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Comment], int]:
        scope = select(Comment).where(Comment.task_id == task_id)
        rows = await self._session.scalars(
            scope.order_by(Comment.created_at, Comment.id).offset(offset).limit(limit)
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(Comment)
            .where(Comment.task_id == task_id)
        )
        return list(rows), total or 0

    async def get(self, comment_id: UUID) -> Comment | None:
        return await self._session.get(Comment, comment_id)

    async def get_for_update(self, comment_id: UUID) -> Comment | None:
        return await self._session.scalar(
            select(Comment)
            .where(Comment.id == comment_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def update(self, comment: Comment, content: str) -> Comment:
        comment.content = content
        await self._session.flush()
        await self._session.refresh(comment)
        return comment

    async def delete(self, comment: Comment) -> None:
        await self._session.delete(comment)
        await self._session.flush()
