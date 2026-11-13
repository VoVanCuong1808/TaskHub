"""Task-comment HTTP adapters."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.pagination import PaginationDep
from app.api.responses import error_responses
from app.core.deps import CurrentUserDep, TaskServiceDep
from app.schemas.comment import CommentCreate, CommentRead, CommentUpdate
from app.schemas.common import Page

router = APIRouter(tags=["comments"])


@router.post(
    "/tasks/{task_id}/comments",
    response_model=CommentRead,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
)
async def create_comment(
    task_id: UUID,
    payload: CommentCreate,
    service: TaskServiceDep,
    user: CurrentUserDep,
) -> CommentRead:
    return CommentRead.model_validate(
        await service.create_comment(task_id, user.id, payload.content)
    )


@router.get(
    "/tasks/{task_id}/comments",
    response_model=Page[CommentRead],
    responses=error_responses(401, 404, 422),
)
async def list_comments(
    task_id: UUID,
    service: TaskServiceDep,
    user: CurrentUserDep,
    pagination: PaginationDep,
) -> Page[CommentRead]:
    comments, total = await service.list_comments(
        task_id,
        user.id,
        offset=pagination.effective_offset,
        limit=pagination.limit,
    )
    return Page[CommentRead](
        items=[CommentRead.model_validate(comment) for comment in comments], total=total
    )


@router.get(
    "/comments/{comment_id}",
    response_model=CommentRead,
    responses=error_responses(401, 404, 422),
)
async def get_comment(
    comment_id: UUID, service: TaskServiceDep, user: CurrentUserDep
) -> CommentRead:
    return CommentRead.model_validate(
        await service.get_comment(comment_id, user.id)
    )


@router.patch(
    "/comments/{comment_id}",
    response_model=CommentRead,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
)
async def update_comment(
    comment_id: UUID,
    payload: CommentUpdate,
    service: TaskServiceDep,
    user: CurrentUserDep,
) -> CommentRead:
    return CommentRead.model_validate(
        await service.update_comment(comment_id, user.id, payload.content)
    )


@router.delete(
    "/comments/{comment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
)
async def delete_comment(
    comment_id: UUID, service: TaskServiceDep, user: CurrentUserDep
) -> Response:
    await service.delete_comment(comment_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

