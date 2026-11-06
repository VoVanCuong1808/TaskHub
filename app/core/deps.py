"""Dependency-injection wiring.

Request-scoped dependencies are built from application singletons stored on
``app.state`` (see :func:`app.main.create_app`).
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request

from app.core.config import Settings, get_settings
from app.repositories.task_repo import TaskRepository
from app.services.task_service import TaskService


def get_task_repository(request: Request) -> TaskRepository:
    repository = getattr(request.app.state, "task_repository", None)
    if repository is None:  # pragma: no cover - misconfiguration guard
        raise RuntimeError("task_repository is not configured on app.state")
    return cast(TaskRepository, repository)


def get_task_service(
    repository: Annotated[TaskRepository, Depends(get_task_repository)],
) -> TaskService:
    return TaskService(repository)


SettingsDep = Annotated[Settings, Depends(get_settings)]
TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]
