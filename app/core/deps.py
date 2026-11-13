"""Dependency-injection wiring.

Request-scoped dependencies are built from application singletons stored on
``app.state`` (see :func:`app.main.create_app`).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.constants import AUTH_NOT_AUTHENTICATED_MESSAGE
from app.core.exceptions import AuthenticationError
from app.db.base import get_db
from app.db.task_uow import SQLAlchemyTaskManagementUnitOfWork
from app.db.workspace_uow import SQLAlchemyWorkspaceUnitOfWork
from app.models.entities import User
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService
from app.services.task_service import TaskService
from app.services.task_uow import TaskManagementUnitOfWork
from app.services.workspace_service import WorkspaceService
from app.services.workspace_uow import WorkspaceUnitOfWork


def get_task_unit_of_work(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> TaskManagementUnitOfWork:
    return SQLAlchemyTaskManagementUnitOfWork(session)


def get_task_service(
    uow: Annotated[TaskManagementUnitOfWork, Depends(get_task_unit_of_work)],
) -> TaskService:
    return TaskService(uow)


TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


SettingsDep = Annotated[Settings, Depends(get_app_settings)]

bearer_scheme = HTTPBearer(auto_error=False)


def get_user_repository(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> UserRepository:
    return UserRepository(session)


def get_auth_service(
    repository: Annotated[UserRepository, Depends(get_user_repository)],
    settings: SettingsDep,
) -> AuthService:
    if settings.jwt_secret_key is None:
        raise RuntimeError("TASKHUB_JWT_SECRET_KEY must be configured")
    return AuthService(
        repository,
        secret=settings.jwt_secret_key.get_secret_value(),
        access_minutes=settings.access_token_minutes,
        refresh_days=settings.refresh_token_days,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    service: AuthServiceDep,
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError(AUTH_NOT_AUTHENTICATED_MESSAGE)
    return await service.authenticate_access(credentials.credentials)


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def get_workspace_unit_of_work(
    session: Annotated[AsyncSession, Depends(get_db)],
) -> WorkspaceUnitOfWork:
    return SQLAlchemyWorkspaceUnitOfWork(session)


def get_workspace_service(
    uow: Annotated[WorkspaceUnitOfWork, Depends(get_workspace_unit_of_work)],
) -> WorkspaceService:
    return WorkspaceService(uow)


WorkspaceServiceDep = Annotated[WorkspaceService, Depends(get_workspace_service)]
