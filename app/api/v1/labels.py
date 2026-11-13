"""Label and task-label HTTP adapters."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.pagination import PaginationDep
from app.api.responses import error_responses
from app.core.deps import CurrentUserDep, TaskServiceDep
from app.schemas.common import Page
from app.schemas.label import LabelCreate, LabelRead, LabelUpdate

router = APIRouter(tags=["labels"])


@router.post(
    "/labels",
    response_model=LabelRead,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
)
async def create_label(
    payload: LabelCreate, service: TaskServiceDep, user: CurrentUserDep
) -> LabelRead:
    return LabelRead.model_validate(
        await service.create_label(user_id=user.id, **payload.model_dump())
    )


@router.get(
    "/labels",
    response_model=Page[LabelRead],
    responses=error_responses(401, 404, 422),
)
async def list_labels(
    service: TaskServiceDep,
    user: CurrentUserDep,
    project_id: Annotated[UUID, Query(description="Project scope")],
    pagination: PaginationDep,
) -> Page[LabelRead]:
    labels, total = await service.list_labels(
        project_id=project_id,
        user_id=user.id,
        offset=pagination.effective_offset,
        limit=pagination.limit,
    )
    return Page[LabelRead](
        items=[LabelRead.model_validate(label) for label in labels], total=total
    )


@router.get(
    "/labels/{label_id}",
    response_model=LabelRead,
    responses=error_responses(401, 404, 422),
)
async def get_label(
    label_id: UUID, service: TaskServiceDep, user: CurrentUserDep
) -> LabelRead:
    return LabelRead.model_validate(await service.get_label(label_id, user.id))


@router.patch(
    "/labels/{label_id}",
    response_model=LabelRead,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
)
async def update_label(
    label_id: UUID,
    payload: LabelUpdate,
    service: TaskServiceDep,
    user: CurrentUserDep,
) -> LabelRead:
    return LabelRead.model_validate(
        await service.update_label(
            label_id, payload.model_dump(exclude_unset=True), user.id
        )
    )


@router.delete(
    "/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
)
async def delete_label(
    label_id: UUID, service: TaskServiceDep, user: CurrentUserDep
) -> Response:
    await service.delete_label(label_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/tasks/{task_id}/labels",
    response_model=Page[LabelRead],
    responses=error_responses(401, 404, 422),
)
async def list_task_labels(
    task_id: UUID,
    service: TaskServiceDep,
    user: CurrentUserDep,
    pagination: PaginationDep,
) -> Page[LabelRead]:
    labels, total = await service.list_task_labels(
        task_id,
        user.id,
        offset=pagination.effective_offset,
        limit=pagination.limit,
    )
    return Page[LabelRead](
        items=[LabelRead.model_validate(label) for label in labels], total=total
    )


@router.put(
    "/tasks/{task_id}/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
)
async def attach_label(
    task_id: UUID,
    label_id: UUID,
    service: TaskServiceDep,
    user: CurrentUserDep,
) -> Response:
    await service.attach_label(task_id, label_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/tasks/{task_id}/labels/{label_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
)
async def detach_label(
    task_id: UUID,
    label_id: UUID,
    service: TaskServiceDep,
    user: CurrentUserDep,
) -> Response:
    await service.detach_label(task_id, label_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

