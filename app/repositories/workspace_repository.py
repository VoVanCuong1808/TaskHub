"""Persistence and authorization boundary for workspaces."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authorization import (
    is_workspace_write_permission,
)
from app.core.constants import (
    WORKSPACE_ALREADY_MEMBER_MESSAGE,
    WORKSPACE_OWNER_ALREADY_MEMBER_MESSAGE,
    WORKSPACE_OWNER_REMOVE_MESSAGE,
    WORKSPACE_OWNER_ROLE_CHANGE_MESSAGE,
    WORKSPACE_OWNER_ROLE_RESERVED_MESSAGE,
)
from app.core.exceptions import (
    WorkspaceConflictError,
    WorkspaceMemberNotFoundError,
    WorkspaceNotFoundError,
)
from app.models.entities import User, Workspace, WorkspaceMember
from app.models.enums import WorkspacePermission, WorkspaceRole
from app.services.workspace_authorization import (
    WorkspaceAuthorizationContext,
    authorize_workspace_access,
)


class WorkspaceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()

    async def add(self, workspace: Workspace, owner: User) -> Workspace:
        self._session.add(workspace)
        await self._session.flush()
        self._session.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=owner.id,
                role=WorkspaceRole.OWNER,
            )
        )
        await self._session.flush()
        return workspace

    async def list_visible(self, user_id: UUID) -> list[Workspace]:
        rows = await self._session.scalars(
            select(Workspace)
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
            .distinct()
            .order_by(Workspace.created_at.desc(), Workspace.id.desc())
        )
        return list(rows)

    async def authorize(
        self,
        workspace_id: UUID,
        user_id: UUID,
        permission: WorkspacePermission,
    ) -> Workspace:
        is_write = is_workspace_write_permission(permission)
        workspace_query = select(Workspace).where(Workspace.id == workspace_id)
        if is_write:
            workspace_query = workspace_query.with_for_update()
        workspace = await self._session.scalar(
            workspace_query.execution_options(populate_existing=True)
        )
        if workspace is None:
            raise WorkspaceNotFoundError()

        # Keep membership lookup separate to preserve workspace-first locking
        # and allow owners whose legacy workspace has no membership row.
        member_query = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
        )
        if is_write:
            member_query = member_query.with_for_update()
        member = await self._session.scalar(
            member_query.execution_options(populate_existing=True)
        )
        authorize_workspace_access(
            WorkspaceAuthorizationContext(
                workspace.owner_id, member.role if member else None
            ),
            user_id,
            permission,
        )
        return workspace

    async def list_members(
        self, workspace_id: UUID, user_id: UUID
    ) -> list[WorkspaceMember]:
        await self.authorize(
            workspace_id, user_id, WorkspacePermission.MEMBER_READ
        )
        rows = await self._session.scalars(
            select(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.created_at, WorkspaceMember.user_id)
        )
        return list(rows)

    async def add_member(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        email: str,
        role: WorkspaceRole,
    ) -> WorkspaceMember:
        workspace = await self.authorize(
            workspace_id, actor_id, WorkspacePermission.MEMBER_INVITE
        )
        user = await self._session.scalar(
            select(User).where(User.email == email, User.is_active.is_(True))
        )
        if user is None:
            raise WorkspaceMemberNotFoundError()
        if user.id == workspace.owner_id:
            raise WorkspaceConflictError(WORKSPACE_OWNER_ALREADY_MEMBER_MESSAGE)
        existing = await self._session.get(
            WorkspaceMember, (workspace_id, user.id)
        )
        if existing is not None:
            raise WorkspaceConflictError(WORKSPACE_ALREADY_MEMBER_MESSAGE)
        if role is WorkspaceRole.OWNER:
            raise WorkspaceConflictError(WORKSPACE_OWNER_ROLE_RESERVED_MESSAGE)
        member = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=user.id,
            role=role,
        )
        self._session.add(member)
        await self._session.flush()
        return member

    async def _get_member_for_update(
        self, workspace_id: UUID, user_id: UUID, owner_id: UUID
    ) -> WorkspaceMember:
        if user_id == owner_id:
            # authorize() already locked the actor's owner membership if present.
            member = await self._session.get(
                WorkspaceMember, (workspace_id, user_id)
            )
        else:
            member = await self._session.scalar(
                select(WorkspaceMember)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id == user_id,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        if member is None:
            raise WorkspaceMemberNotFoundError()
        return member

    async def update_member(
        self,
        workspace_id: UUID,
        actor_id: UUID,
        user_id: UUID,
        role: WorkspaceRole,
    ) -> WorkspaceMember:
        workspace = await self.authorize(
            workspace_id, actor_id, WorkspacePermission.MEMBER_UPDATE
        )
        member = await self._get_member_for_update(
            workspace_id, user_id, workspace.owner_id
        )
        if user_id == workspace.owner_id:
            raise WorkspaceConflictError(WORKSPACE_OWNER_ROLE_CHANGE_MESSAGE)
        if role is WorkspaceRole.OWNER:
            raise WorkspaceConflictError(WORKSPACE_OWNER_ROLE_RESERVED_MESSAGE)
        member.role = role
        await self._session.flush()
        return member

    async def remove_member(
        self, workspace_id: UUID, actor_id: UUID, user_id: UUID
    ) -> None:
        workspace = await self.authorize(
            workspace_id, actor_id, WorkspacePermission.MEMBER_REMOVE
        )
        member = await self._get_member_for_update(
            workspace_id, user_id, workspace.owner_id
        )
        if user_id == workspace.owner_id:
            raise WorkspaceConflictError(WORKSPACE_OWNER_REMOVE_MESSAGE)
        await self._session.delete(member)
        await self._session.flush()

    async def delete(self, workspace: Workspace) -> None:
        await self._session.delete(workspace)
        await self._session.flush()
