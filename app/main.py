"""TaskHub application factory (composition root).

Run with:
    uv run uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.v1.router import api_router
from app.api.v1.tasks import router as tasks_router
from app.core.config import Settings, get_settings
from app.core.constants import (
    INTEGRITY_CONFLICT_MESSAGE,
    INTEGRITY_INVALID_MESSAGE,
    INTEGRITY_REFERENCE_MESSAGE,
    INTEGRITY_REQUIRED_MESSAGE,
    INTEGRITY_RESTRICTED_MESSAGE,
)
from app.core.exceptions import AuthenticationError, TaskNotFoundError
from app.db.base import make_engine, make_session_factory
from app.db.seed import seed_default_data

logger = logging.getLogger("taskhub")
RESTRICTED_DELETE_CONSTRAINTS = {
    "comments_author_id_fkey",
    "tasks_created_by_fkey",
    "workspaces_owner_id_fkey",
}


def _postgres_error_attribute(error: object, name: str) -> object | None:
    visited = set()
    current = error
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        value = getattr(current, name, None)
        if value is not None:
            return value
        current = getattr(current, "__cause__", None)
    return None


def _configure_logging(settings: Settings) -> None:
    level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )


def integrity_error_response(request: Request, exc: IntegrityError) -> JSONResponse:
    sqlstate = _postgres_error_attribute(exc.orig, "sqlstate") or (
        _postgres_error_attribute(exc.orig, "pgcode")
    )
    constraint_name = _postgres_error_attribute(exc.orig, "constraint_name")
    is_delete = bool(
        exc.statement and exc.statement.lstrip().upper().startswith("DELETE")
    )
    if sqlstate == "23505":
        logger.warning("Integrity conflict on %s", request.url.path)
        return JSONResponse(
            status_code=409, content={"detail": INTEGRITY_CONFLICT_MESSAGE}
        )
    if (
        sqlstate == "23503"
        and is_delete
        and constraint_name in RESTRICTED_DELETE_CONSTRAINTS
    ):
        logger.warning("Delete restricted on %s", request.url.path)
        return JSONResponse(
            status_code=409, content={"detail": INTEGRITY_RESTRICTED_MESSAGE}
        )
    if sqlstate == "23503":
        logger.warning("Invalid reference on %s", request.url.path)
        return JSONResponse(
            status_code=422, content={"detail": INTEGRITY_REFERENCE_MESSAGE}
        )
    if sqlstate == "23502":
        logger.warning("Missing required database value on %s", request.url.path)
        message = INTEGRITY_REQUIRED_MESSAGE
    else:
        logger.warning("Invalid database constraint on %s", request.url.path)
        message = INTEGRITY_INVALID_MESSAGE
    return JSONResponse(status_code=422, content={"detail": message})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully wired FastAPI application."""
    settings = settings or get_settings()
    _configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        secret = settings.jwt_secret_key
        if secret is None or len(secret.get_secret_value().encode("utf-8")) < 32:
            raise RuntimeError("TASKHUB_JWT_SECRET_KEY must contain at least 32 bytes")
        app.state.engine = make_engine(
            settings.database_url, echo=settings.database_echo
        )
        app.state.session_factory = make_session_factory(app.state.engine)
        try:
            await seed_default_data(app.state.session_factory)
            logger.info(
                "TaskHub starting | env=%s version=%s docs=/docs",
                settings.environment,
                settings.version,
            )
            yield
        finally:
            await app.state.engine.dispose()
            logger.info("TaskHub shutting down")

    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Layered FastAPI skeleton: api -> services -> repositories.",
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.frontend_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(TaskNotFoundError)
    async def task_not_found_handler(
        request: Request, exc: TaskNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(AuthenticationError)
    async def authentication_error_handler(
        request: Request, exc: AuthenticationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=401,
            headers={"WWW-Authenticate": "Bearer"},
            content={"detail": str(exc)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: error[key] for key in ("loc", "msg", "type") if key in error}
                    for error in exc.errors()
                ]
            },
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error_handler(
        request: Request, exc: IntegrityError
    ) -> JSONResponse:
        return integrity_error_response(request, exc)

    @app.get("/health", tags=["system"], summary="Liveness probe")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
        }

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    app.include_router(tasks_router, include_in_schema=False)

    return app


app = create_app()
