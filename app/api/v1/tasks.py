"""Task endpoints (HTTP adapter only: validate, delegate, serialize)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query, Response, status

from app.core.constants import TASK_NOT_FOUND_DESCRIPTION
from app.core.deps import TaskServiceDep
from app.models.task import TaskStatus
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])

NOT_FOUND_RESPONSE = {404: {"description": TASK_NOT_FOUND_DESCRIPTION}}


@router.post(
    "",
    response_model=TaskRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a task",
)
def create_task(payload: TaskCreate, service: TaskServiceDep) -> TaskRead:
    return TaskRead.model_validate(service.create(payload))


@router.get("", response_model=list[TaskRead], summary="List tasks")
def list_tasks(
    service: TaskServiceDep,
    task_status: Annotated[
        TaskStatus | None, Query(alias="status", description="Filter by status")
    ] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[TaskRead]:
    tasks = service.list(status=task_status, offset=offset, limit=limit)
    return [TaskRead.model_validate(task) for task in tasks]


@router.get(
    "/{task_id}",
    response_model=TaskRead,
    responses=NOT_FOUND_RESPONSE,
    summary="Get a task",
)
def get_task(task_id: UUID, service: TaskServiceDep) -> TaskRead:
    return TaskRead.model_validate(service.get(task_id))


@router.patch(
    "/{task_id}",
    response_model=TaskRead,
    responses=NOT_FOUND_RESPONSE,
    summary="Partially update a task",
)
def update_task(
    task_id: UUID, payload: TaskUpdate, service: TaskServiceDep
) -> TaskRead:
    return TaskRead.model_validate(service.update(task_id, payload))


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=NOT_FOUND_RESPONSE,
    summary="Delete a task",
)
def delete_task(task_id: UUID, service: TaskServiceDep) -> Response:
    service.delete(task_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
