"""SQL persistence for workspace project records."""

from uuid import UUID

from sqlalchemy import func, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.constants import DEFAULT_PAGE_LIMIT
from app.models.entities import Project
from app.models.enums import ProjectStatus


class ProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, project: Project) -> Project:
        self._session.add(project)
        await self._session.flush()
        await self._session.refresh(project)
        return project

    async def get(self, project_id: UUID) -> Project | None:
        return await self._session.get(Project, project_id)

    async def get_for_share(self, project_id: UUID) -> Project | None:
        return await self._session.scalar(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )

    async def get_for_update(self, project_id: UUID) -> Project | None:
        return await self._session.scalar(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def list(
        self, workspace_id: UUID, *, offset: int, limit: int = DEFAULT_PAGE_LIMIT
    ) -> tuple[list[Project], int]:
        total = (
            select(func.count().label("total"))
            .where(Project.workspace_id == workspace_id)
            .subquery()
        )
        page = (
            select(Project)
            .where(Project.workspace_id == workspace_id)
            .order_by(Project.created_at.desc(), Project.id.desc())
            .offset(offset)
            .limit(limit)
            .subquery()
        )
        page_project = aliased(Project, page)
        result = await self._session.execute(
            select(page_project, total.c.total)
            .select_from(total.outerjoin(page, true()))
            .order_by(page_project.created_at.desc(), page_project.id.desc())
        )
        rows = result.all()
        return [project for project, _ in rows if project is not None], rows[0][1]

    async def update(
        self,
        project: Project,
        *,
        name: str,
        description: str | None,
        status: ProjectStatus,
    ) -> Project:
        project.name = name
        project.description = description
        project.status = status
        await self._session.flush()
        await self._session.refresh(project)
        return project

    async def delete(self, project: Project) -> None:
        await self._session.delete(project)
        await self._session.flush()
