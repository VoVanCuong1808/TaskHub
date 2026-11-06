"""Dependency-injection wiring.

Request-scoped dependencies are built from application singletons stored on
``app.state`` (see :func:`app.main.create_app`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.base import get_db
from app.repositories.task_database import TaskRepository
from app.services.task_service import TaskService


def get_task_repository(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TaskRepository:
    return TaskRepository(session)


def get_task_service(
    repository: Annotated[TaskRepository, Depends(get_task_repository)],
) -> TaskService:
    return TaskService(repository)


SettingsDep = Annotated[Settings, Depends(get_settings)]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
