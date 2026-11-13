"""Task endpoints (HTTP adapter only: validate, delegate, serialize)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.api.pagination import PaginationDep
from app.api.responses import error_responses
from app.core.deps import CurrentUserDep, TaskServiceDep
from app.models.enums import TaskPriority, TaskStatus
from app.schemas.common import Page
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])

@router.post(
    "",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
    summary="Create a task",
    description="Requires a Bearer access token and an accessible project_id. Workspace owners and editors can create tasks.",
)
async def create_task(
    payload: TaskCreate, service: TaskServiceDep, user: CurrentUserDep
) -> TaskRead:
    return TaskRead.model_validate(
        await service.create(user_id=user.id, **payload.model_dump())
    )


@router.get(
    "",
    response_model=Page[TaskRead],
    responses=error_responses(401, 404, 422),
    summary="List tasks",
    description=(
        "Requires a Bearer access token and project_id for a workspace you can "
        "access. Combine status, priority, and assignee_id filters with AND. "
        "Use one-based page with limit. Offset pagination is no longer supported."
    ),
)
async def list_tasks(
    service: TaskServiceDep,
    user: CurrentUserDep,
    project_id: Annotated[UUID, Query(description="Project scope")],
    pagination: PaginationDep,
    task_status: Annotated[
        TaskStatus | None, Query(alias="status", description="Filter by status")
    ] = None,
    priority: Annotated[
        TaskPriority | None, Query(description="Filter by priority")
    ] = None,
    assignee_id: Annotated[
        UUID | None, Query(description="Filter by assigned user")
    ] = None,
) -> Page[TaskRead]:
    tasks, total = await service.list(
        project_id=project_id,
        user_id=user.id,
        status=task_status,
        priority=priority,
        assignee_id=assignee_id,
        offset=pagination.effective_offset,
        limit=pagination.limit,
    )
    return Page[TaskRead](
        items=[TaskRead.model_validate(task) for task in tasks], total=total
    )


@router.get(
    "/{task_id}",
    response_model=TaskRead,
    responses=error_responses(401, 404, 422),
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
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
    summary="Partially update a task",
    description="Requires a Bearer access token and an owner or editor role in the task workspace.",
)
async def update_task(
    task_id: UUID, payload: TaskUpdate, service: TaskServiceDep, user: CurrentUserDep
) -> TaskRead:
    return TaskRead.model_validate(
        await service.update(
            task_id, payload.model_dump(exclude_unset=True), user.id
        )
    )


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
    summary="Delete a task",
    description="Requires a Bearer access token and an owner or editor role in the task workspace.",
)
async def delete_task(
    task_id: UUID, service: TaskServiceDep, user: CurrentUserDep
) -> Response:
    await service.delete(task_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
