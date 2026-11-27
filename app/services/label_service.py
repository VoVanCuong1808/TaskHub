"""Project labels and task-label association use cases."""

from collections.abc import Mapping
from typing import cast
from uuid import UUID

from app.core.constants import DEFAULT_PAGE_LIMIT
from app.core.exceptions import TaskLabelNotFoundError
from app.models.entities import Label
from app.models.enums import WorkspacePermission
from app.services.task_access import TaskAccess
from app.services.task_uow import TaskManagementUnitOfWork
from app.services.transaction import transaction_scope

LABEL_UPDATE_FIELDS = frozenset({"name", "color"})


class LabelService:
    def __init__(self, uow: TaskManagementUnitOfWork) -> None:
        self._uow = uow
        self._access = TaskAccess(uow)

    async def create_label(
        self, *, project_id: UUID, user_id: UUID, name: str, color: str
    ) -> Label:
        async with transaction_scope(self._uow, "Task transaction failed"):
            await self._access.project(
                project_id, user_id, WorkspacePermission.LABEL_CREATE, write=True
            )
            return await self._uow.labels.add(
                Label(project_id=project_id, name=name, color=color)
            )

    async def list_labels(
        self,
        *,
        project_id: UUID,
        user_id: UUID,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[Label], int]:
        await self._access.project(
            project_id, user_id, WorkspacePermission.LABEL_READ, write=False
        )
        return await self._uow.labels.list(project_id, offset=offset, limit=limit)

    async def get_label(self, label_id: UUID, user_id: UUID) -> Label:
        label, _ = await self._access.label(
            label_id, user_id, WorkspacePermission.LABEL_READ, write=False
        )
        return label

    async def update_label(
        self, label_id: UUID, changes: Mapping[str, object], user_id: UUID
    ) -> Label:
        if changes.keys() - LABEL_UPDATE_FIELDS:
            raise ValueError("Unsupported label fields")
        async with transaction_scope(self._uow, "Task transaction failed"):
            label, _ = await self._access.label(
                label_id, user_id, WorkspacePermission.LABEL_UPDATE, write=True
            )
            return await self._uow.labels.update(
                label,
                name=cast(str | None, changes.get("name")),
                color=cast(str | None, changes.get("color")),
            )

    async def delete_label(self, label_id: UUID, user_id: UUID) -> None:
        async with transaction_scope(self._uow, "Task transaction failed"):
            label, _ = await self._access.label(
                label_id, user_id, WorkspacePermission.LABEL_DELETE, write=True
            )
            await self._uow.labels.delete(label)

    async def list_task_labels(
        self,
        task_id: UUID,
        user_id: UUID,
        *,
        offset: int = 0,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> tuple[list[Label], int]:
        await self._access.task(
            task_id, user_id, WorkspacePermission.LABEL_READ, write=False
        )
        return await self._uow.labels.list_for_task(
            task_id, offset=offset, limit=limit
        )

    async def attach_label(
        self, task_id: UUID, label_id: UUID, user_id: UUID
    ) -> None:
        async with transaction_scope(self._uow, "Task transaction failed"):
            await self._access.task_label(task_id, label_id, user_id)
            await self._uow.labels.attach(task_id, label_id)

    async def detach_label(
        self, task_id: UUID, label_id: UUID, user_id: UUID
    ) -> None:
        async with transaction_scope(self._uow, "Task transaction failed"):
            await self._access.task_label(task_id, label_id, user_id)
            if not await self._uow.labels.detach(task_id, label_id):
                raise TaskLabelNotFoundError()
