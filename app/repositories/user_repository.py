"""Persistence operations for accounts and refresh sessions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import RefreshSession, User


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: User) -> User:
        self._session.add(user)
        await self._session.flush()
        return user

    async def get(self, user_id: UUID) -> User | None:
        return await self._session.get(User, user_id)

    async def get_for_update(self, user_id: UUID) -> User | None:
        return await self._session.scalar(
            select(User)
            .where(User.id == user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def get_by_email(self, email: str) -> User | None:
        return await self._session.scalar(select(User).where(User.email == email))

    async def add_refresh(self, session: RefreshSession) -> None:
        self._session.add(session)
        await self._session.flush()

    async def get_refresh_for_update(self, jti: str) -> RefreshSession | None:
        return await self._session.scalar(
            select(RefreshSession)
            .where(RefreshSession.jti == jti)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def revoke_user_refresh_sessions(self, user_id: UUID, now: datetime) -> None:
        await self._session.execute(
            update(RefreshSession)
            .where(
                RefreshSession.user_id == user_id, RefreshSession.revoked_at.is_(None)
            )
            .values(revoked_at=now)
        )

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
