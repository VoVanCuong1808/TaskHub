"""Workspace management HTTP endpoints."""

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.pagination import PaginationDep
from app.api.responses import error_responses
from app.core.deps import CurrentUserDep, WorkspaceServiceDep
from app.schemas.common import Page
from app.schemas.workspace import (
    WorkspaceCreate,
    WorkspaceMemberCreate,
    WorkspaceMemberRead,
    WorkspaceMemberUpdate,
    WorkspaceRead,
    WorkspaceUpdate,
)

router = APIRouter(
    prefix="/workspaces", tags=["workspaces"]
)


@router.post(
    "",
    response_model=WorkspaceRead,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 422),
)
async def create_workspace(
    payload: WorkspaceCreate, service: WorkspaceServiceDep, user: CurrentUserDep
) -> WorkspaceRead:
    return WorkspaceRead.model_validate(await service.create(payload.name, user.id))


@router.get("", response_model=Page[WorkspaceRead], responses=error_responses(401, 422))
async def list_workspaces(
    service: WorkspaceServiceDep,
    user: CurrentUserDep,
    pagination: PaginationDep,
) -> Page[WorkspaceRead]:
    workspaces, total = await service.list(
        user.id, offset=pagination.effective_offset, limit=pagination.limit
    )
    return Page[WorkspaceRead](
        items=[WorkspaceRead.model_validate(item) for item in workspaces],
        total=total,
    )


@router.get(
    "/{workspace_id}",
    response_model=WorkspaceRead,
    responses=error_responses(401, 404),
)
async def get_workspace(
    workspace_id: UUID, service: WorkspaceServiceDep, user: CurrentUserDep
) -> WorkspaceRead:
    return WorkspaceRead.model_validate(await service.get(workspace_id, user.id))


@router.patch(
    "/{workspace_id}",
    response_model=WorkspaceRead,
    responses=error_responses(401, 403, 404, 422),
)
async def update_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    service: WorkspaceServiceDep,
    user: CurrentUserDep,
) -> WorkspaceRead:
    return WorkspaceRead.model_validate(
        await service.update(workspace_id, user.id, payload.name)
    )


@router.delete(
    "/{workspace_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404),
)
async def delete_workspace(
    workspace_id: UUID, service: WorkspaceServiceDep, user: CurrentUserDep
) -> Response:
    await service.delete(workspace_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{workspace_id}/members",
    response_model=Page[WorkspaceMemberRead],
    responses=error_responses(401, 404, 422),
)
async def list_workspace_members(
    workspace_id: UUID,
    service: WorkspaceServiceDep,
    user: CurrentUserDep,
    pagination: PaginationDep,
) -> Page[WorkspaceMemberRead]:
    members, total = await service.list_members(
        workspace_id,
        user.id,
        offset=pagination.effective_offset,
        limit=pagination.limit,
    )
    return Page[WorkspaceMemberRead](
        items=[WorkspaceMemberRead.model_validate(item) for item in members],
        total=total,
    )


@router.post(
    "/{workspace_id}/members",
    response_model=WorkspaceMemberRead,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
)
async def add_workspace_member(
    workspace_id: UUID,
    payload: WorkspaceMemberCreate,
    service: WorkspaceServiceDep,
    user: CurrentUserDep,
) -> WorkspaceMemberRead:
    return WorkspaceMemberRead.model_validate(
        await service.add_member(
            workspace_id, user.id, str(payload.email), payload.role
        )
    )


@router.patch(
    "/{workspace_id}/members/{user_id}",
    response_model=WorkspaceMemberRead,
    responses=error_responses(401, 403, 404, 409, 422, domain_422=True),
)
async def update_workspace_member(
    workspace_id: UUID,
    user_id: UUID,
    payload: WorkspaceMemberUpdate,
    service: WorkspaceServiceDep,
    user: CurrentUserDep,
) -> WorkspaceMemberRead:
    return WorkspaceMemberRead.model_validate(
        await service.update_member(workspace_id, user.id, user_id, payload.role)
    )


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404, 409),
)
async def remove_workspace_member(
    workspace_id: UUID,
    user_id: UUID,
    service: WorkspaceServiceDep,
    user: CurrentUserDep,
) -> Response:
    await service.remove_member(workspace_id, user.id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
