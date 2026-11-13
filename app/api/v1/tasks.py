"""Task endpoints (HTTP adapter only: validate, delegate, serialize)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.core.constants import TASK_NOT_FOUND_DESCRIPTION
from app.core.deps import CurrentUserDep, TaskServiceDep
from app.models.enums import TaskStatus
from app.schemas.common import Page, PaginationParams
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])

NOT_FOUND_RESPONSE = {404: {"description": TASK_NOT_FOUND_DESCRIPTION}}


@router.post(
    "",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
    description="Requires a Bearer access token and an accessible project_id. Workspace owners and editors can create tasks.",
)
async def create_task(
    payload: TaskCreate, service: TaskServiceDep, user: CurrentUserDep
) -> TaskRead:
    return TaskRead.model_validate(await service.create(payload, user.id))


@router.get(
    "",
    response_model=Page[TaskRead],
    summary="List tasks",
    description="Requires a Bearer access token and project_id for a workspace you can access.",
)
async def list_tasks(
    service: TaskServiceDep,
    user: CurrentUserDep,
    project_id: Annotated[UUID, Query(description="Project scope")],
    pagination: Annotated[PaginationParams, Query()],
    task_status: Annotated[
        TaskStatus | None, Query(alias="status", description="Filter by status")
    ] = None,
) -> Page[TaskRead]:
    tasks, total = await service.list(
        project_id=project_id,
        user_id=user.id,
        status=task_status,
        offset=pagination.offset,
        limit=pagination.limit,
    )
    return Page[TaskRead](
        items=[TaskRead.model_validate(task) for task in tasks], total=total
    )


@router.get(
    "/{task_id}",
    response_model=TaskRead,
    responses=NOT_FOUND_RESPONSE,
    summary="Get a task",
    description="Requires a Bearer access token and workspace visibility for the task.",
)
async def get_task(
    task_id: UUID, service: TaskServiceDep, user: CurrentUserDep
) -> TaskRead:
    return TaskRead.model_validate(await service.get(task_id, user.id))


@router.patch(
    "/{task_id}",
    response_model=TaskRead,
    responses=NOT_FOUND_RESPONSE,
    summary="Partially update a task",
    description="Requires a Bearer access token and an owner or editor role in the task workspace.",
)
async def update_task(
    task_id: UUID, payload: TaskUpdate, service: TaskServiceDep, user: CurrentUserDep
) -> TaskRead:
    return TaskRead.model_validate(await service.update(task_id, payload, user.id))


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND_RESPONSE,
    summary="Delete a task",
    description="Requires a Bearer access token and an owner or editor role in the task workspace.",
)
async def delete_task(
    task_id: UUID, service: TaskServiceDep, user: CurrentUserDep
) -> Response:
    await service.delete(task_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
