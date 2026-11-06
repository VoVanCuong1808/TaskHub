"""TaskHub application factory (composition root).

Run with:
    uv run uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.constants import (
    INTEGRITY_CONFLICT_MESSAGE,
    INTEGRITY_REFERENCE_MESSAGE,
    INTEGRITY_RESTRICTED_MESSAGE,
)
from app.core.exceptions import TaskNotFoundError
from app.db.base import make_engine, make_session_factory

logger = logging.getLogger("taskhub")


def _configure_logging(settings: Settings) -> None:
    level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )


def integrity_error_response(request: Request, exc: IntegrityError) -> JSONResponse:
    detail = str(exc.orig)
    sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)
    if sqlstate == "23505":
        logger.warning("Integrity conflict on %s: %s", request.url.path, detail)
        return JSONResponse(
            status_code=409, content={"detail": INTEGRITY_CONFLICT_MESSAGE}
        )
    if "still referenced" in detail or "update or delete on table" in detail:
        logger.warning("Delete restricted on %s: %s", request.url.path, detail)
        return JSONResponse(
            status_code=409, content={"detail": INTEGRITY_RESTRICTED_MESSAGE}
        )
    logger.warning("Invalid reference on %s: %s", request.url.path, detail)
    return JSONResponse(
        status_code=422, content={"detail": INTEGRITY_REFERENCE_MESSAGE}
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully wired FastAPI application."""
    settings = settings or get_settings()
    _configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = make_engine(
            settings.database_url, echo=settings.database_echo
        )
        app.state.session_factory = make_session_factory(app.state.engine)
        logger.info(
            "TaskHub starting | env=%s version=%s docs=/docs",
            settings.environment,
            settings.version,
        )
        try:
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

    @app.exception_handler(TaskNotFoundError)
    async def task_not_found_handler(
        request: Request, exc: TaskNotFoundError
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

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
    app.include_router(api_router, include_in_schema=False)

    return app


app = create_app()
