"""Project HTTP endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.api.pagination import PaginationDep
from app.api.responses import error_responses
from app.core.deps import CurrentUserDep, ProjectServiceDep
from app.schemas.common import Page
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate

router = APIRouter(tags=["projects"])


@router.post(
    "/workspaces/{workspace_id}/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(401, 403, 404, 422),
    summary="Create a project",
    description=(
        "Requires a Bearer access token and a visible workspace. Workspace owners "
        "and editors can create projects."
    ),
)
async def create_project(
    workspace_id: UUID,
    payload: ProjectCreate,
    service: ProjectServiceDep,
    user: CurrentUserDep,
) -> ProjectRead:
    return ProjectRead.model_validate(
        await service.create(workspace_id=workspace_id, user_id=user.id, **payload.model_dump())
    )


@router.get(
    "/workspaces/{workspace_id}/projects",
    response_model=Page[ProjectRead],
    responses=error_responses(401, 403, 404, 422),
    summary="List projects",
    description=(
        "Requires a Bearer access token and a visible workspace. Results are "
        "ordered newest first and use one-based page with limit. Offset is not supported."
    ),
)
async def list_projects(
    workspace_id: UUID,
    service: ProjectServiceDep,
    user: CurrentUserDep,
    pagination: PaginationDep,
) -> Page[ProjectRead]:
    projects, total = await service.list(
        workspace_id=workspace_id,
        user_id=user.id,
        offset=pagination.effective_offset,
        limit=pagination.limit,
    )
    return Page[ProjectRead](
        items=[ProjectRead.model_validate(project) for project in projects],
        total=total,
    )


@router.get(
    "/projects/{project_id}",
    response_model=ProjectRead,
    responses=error_responses(401, 403, 404),
    summary="Get a project",
    description="Requires a Bearer access token and workspace visibility for the project.",
)
async def get_project(
    project_id: UUID, service: ProjectServiceDep, user: CurrentUserDep
) -> ProjectRead:
    return ProjectRead.model_validate(await service.get(project_id, user.id))


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectRead,
    responses=error_responses(401, 403, 404, 422),
    summary="Update, archive or restore a project",
    description=(
        "Requires a Bearer access token. Owners and editors may update project "
        "metadata and set status to active or archived."
    ),
)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    service: ProjectServiceDep,
    user: CurrentUserDep,
) -> ProjectRead:
    return ProjectRead.model_validate(
        await service.update(project_id, payload.model_dump(exclude_unset=True), user.id)
    )


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 403, 404),
    summary="Delete a project",
    description=(
        "Requires a Bearer access token. Owners and editors may delete a project; "
        "its tasks, labels, links, and comments are removed by database cascades."
    ),
)
async def delete_project(
    project_id: UUID, service: ProjectServiceDep, user: CurrentUserDep
) -> Response:
    await service.delete(project_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
