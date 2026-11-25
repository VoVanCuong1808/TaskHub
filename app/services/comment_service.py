"""Task comment use cases and author-only mutation policy."""

from uuid import UUID

from app.core.constants import DEFAULT_PAGE_LIMIT
from app.models.entities import Comment
from app.models.enums import WorkspacePermission
from app.services.task_access import TaskAccess
from app.services.task_authorization import authorize_comment_author
from app.services.task_uow import TaskManagementUnitOfWork
from app.services.transaction import transaction_scope


class CommentService:
    def __init__(self, uow: TaskManagementUnitOfWork) -> None:
        self._uow = uow
        self._access = TaskAccess(uow)

    async def create_comment(
        self, task_id: UUID, user_id: UUID, content: str
    ) -> Comment:
        async with transaction_scope(self._uow, "Task transaction failed"):
            await self._access.task(
                task_id, user_id, WorkspacePermission.COMMENT_CREATE, write=True
            )
            return await self._uow.comments.add(
                Comment(task_id=task_id, author_id=user_id, content=content)
            )

    async def list_comments(
        self,
        task_id: UUID,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[Comment], int]:
        await self._access.task(
            task_id, user_id, WorkspacePermission.COMMENT_READ, write=False
        )
        return await self._uow.comments.list_for_task(
            task_id, offset=offset, limit=limit
        )

    async def get_comment(self, comment_id: UUID, user_id: UUID) -> Comment:
        return await self._access.comment(
            comment_id, user_id, WorkspacePermission.COMMENT_READ, write=False
        )

    async def update_comment(
        self, comment_id: UUID, user_id: UUID, content: str
    ) -> Comment:
        async with transaction_scope(self._uow, "Task transaction failed"):
            comment = await self._access.comment(
                comment_id, user_id, WorkspacePermission.COMMENT_UPDATE, write=True
            )
            authorize_comment_author(comment.author_id, user_id)
            return await self._uow.comments.update(comment, content)

    async def delete_comment(self, comment_id: UUID, user_id: UUID) -> None:
        async with transaction_scope(self._uow, "Task transaction failed"):
            comment = await self._access.comment(
                comment_id, user_id, WorkspacePermission.COMMENT_DELETE, write=True
            )
            authorize_comment_author(comment.author_id, user_id)
            await self._uow.comments.delete(comment)
