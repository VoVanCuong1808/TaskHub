"""TaskHub application factory (composition root).

Run with:
    uv run uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import TaskNotFoundError
from app.repositories.task_repo import InMemoryTaskRepository

logger = logging.getLogger("taskhub")


def _configure_logging(settings: Settings) -> None:
    level = logging.DEBUG if settings.debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a fully wired FastAPI application."""
    settings = settings or get_settings()
    _configure_logging(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.task_repository = InMemoryTaskRepository()
        logger.info(
            "TaskHub starting | env=%s version=%s docs=/docs",
            settings.environment,
            settings.version,
        )
        try:
            yield
        finally:
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

    @app.get("/health", tags=["system"], summary="Liveness probe")
    async def health() -> dict[str, str]:
        return {
            "status": "ok",
            "app": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
        }

    # Versioned canonical surface: /api/v1/tasks
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    # Short alias: /tasks (hidden from the schema to avoid duplicate operations).
    app.include_router(api_router, include_in_schema=False)

    return app


app = create_app()
