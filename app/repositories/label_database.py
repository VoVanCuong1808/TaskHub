"""SQL-only persistence store for project labels and task-label links."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Label, TaskLabel


class LabelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, label: Label) -> Label:
        self._session.add(label)
        await self._session.flush()
        return label

    async def list(
        self, project_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Label], int]:
        scope = select(Label).where(Label.project_id == project_id)
        rows = await self._session.scalars(
            scope.order_by(Label.created_at, Label.id).offset(offset).limit(limit)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(Label).where(Label.project_id == project_id)
        )
        return list(rows), total or 0

    async def list_for_task(
        self, task_id: UUID, *, offset: int, limit: int
    ) -> tuple[list[Label], int]:
        scope = (
            select(Label)
            .join(TaskLabel, TaskLabel.label_id == Label.id)
            .where(TaskLabel.task_id == task_id)
        )
        rows = await self._session.scalars(
            scope.order_by(TaskLabel.created_at, TaskLabel.label_id)
            .offset(offset)
            .limit(limit)
        )
        total = await self._session.scalar(
            select(func.count())
            .select_from(TaskLabel)
            .where(TaskLabel.task_id == task_id)
        )
        return list(rows), total or 0

    async def get(self, label_id: UUID) -> Label | None:
        return await self._session.get(Label, label_id)

    async def get_for_update(self, label_id: UUID) -> Label | None:
        return await self._session.scalar(
            select(Label)
            .where(Label.id == label_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    async def update(
        self, label: Label, *, name: str | None, color: str | None
    ) -> Label:
        if name is not None:
            label.name = name
        if color is not None:
            label.color = color
        await self._session.flush()
        await self._session.refresh(label)
        return label

    async def delete(self, label: Label) -> None:
        await self._session.delete(label)
        await self._session.flush()

    async def attach(self, task_id: UUID, label_id: UUID) -> None:
        await self._session.execute(
            insert(TaskLabel)
            .values(task_id=task_id, label_id=label_id)
            .on_conflict_do_nothing(
                index_elements=[TaskLabel.task_id, TaskLabel.label_id]
            )
        )
        await self._session.flush()

    async def detach(self, task_id: UUID, label_id: UUID) -> bool:
        result = await self._session.execute(
            delete(TaskLabel).where(
                TaskLabel.task_id == task_id, TaskLabel.label_id == label_id
            )
        )
        await self._session.flush()
        return bool(result.rowcount)
