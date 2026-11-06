"""Generic asynchronous SQLAlchemy repository."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base


class BaseRepository[Model: Base]:
    """CRUD operations for one SQLAlchemy model."""

    def __init__(self, session: AsyncSession, model: type[Model]) -> None:
        self.session = session
        self.model = model

    async def get(self, item_id):
        return await self.session.get(self.model, item_id)

    async def list(self, *, offset: int = 0, limit: int = 100) -> list[Model]:
        result = await self.session.scalars(
            select(self.model).offset(offset).limit(limit)
        )
        return list(result)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

    async def create(self, item: Model) -> Model:
        self.session.add(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def update(self, item: Model) -> Model:
        item = await self.session.merge(item)
        await self.session.flush()
        await self.session.refresh(item)
        return item

    async def delete(self, item_id) -> bool:
        item = await self.get(item_id)
        if item is None:
            return False
        await self.session.delete(item)
        await self.session.flush()
        return True

    async def count(self) -> int:
        return (
            await self.session.scalar(select(func.count()).select_from(self.model)) or 0
        )
