"""SQL persistence adapter for workspace rows."""

from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Workspace, WorkspaceMember
from app.models.enums import WorkspaceRole


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, workspace: Workspace) -> Workspace:
        self._session.add(workspace)
        await self._session.flush()
        return workspace

    async def add_member(self, member: WorkspaceMember) -> WorkspaceMember:
        self._session.add(member)
        await self._session.flush()
        return member

    async def update(self, workspace: Workspace, name: str) -> Workspace:
        workspace.name = name
        await self._session.flush()
        return workspace

    async def get(self, workspace_id: UUID) -> Workspace | None:
        return await self._session.get(Workspace, workspace_id)

    async def get_for_update(self, workspace_id: UUID) -> Workspace | None:
        return await self._session.scalar(
            select(Workspace)
            .where(Workspace.id == workspace_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def get_member(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None:
        return await self._session.get(WorkspaceMember, (workspace_id, user_id))

    async def get_member_for_update(
        self, workspace_id: UUID, user_id: UUID
    ) -> WorkspaceMember | None:
        return await self._session.scalar(
            select(WorkspaceMember)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def list_visible(
        self, user_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Workspace], int]:
        visible = select(Workspace).outerjoin(
            WorkspaceMember,
            (WorkspaceMember.workspace_id == Workspace.id)
            & (WorkspaceMember.user_id == user_id),
        ).where(
            or_(
                Workspace.owner_id == user_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        rows = await self._session.scalars(
            visible.order_by(Workspace.created_at.desc(), Workspace.id.desc())
            .offset(offset)
            .limit(limit)
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(Workspace)
            .outerjoin(
                WorkspaceMember,
                (WorkspaceMember.workspace_id == Workspace.id)
                & (WorkspaceMember.user_id == user_id),
            )
            .where(
                or_(
                    Workspace.owner_id == user_id,
                    WorkspaceMember.user_id == user_id,
                )
            )
        )
        return list(rows), total or 0

    async def list_members(
        self, workspace_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[WorkspaceMember], int]:
        query = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id
        )
        rows = await self._session.scalars(
            query.order_by(
                WorkspaceMember.created_at, WorkspaceMember.user_id
            )
            .offset(offset)
            .limit(limit)
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
        )
        return list(rows), total or 0

    async def update_member(
        self, member: WorkspaceMember, role: WorkspaceRole
    ) -> WorkspaceMember:
        member.role = role
        await self._session.flush()
        return member

    async def delete_member(self, member: WorkspaceMember) -> None:
        await self._session.delete(member)
        await self._session.flush()

    async def delete(self, workspace: Workspace) -> None:
        await self._session.delete(workspace)
        await self._session.flush()
