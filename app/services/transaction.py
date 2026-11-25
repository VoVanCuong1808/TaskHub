"""Small transaction scope shared by application services."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Protocol

from app.core.exceptions import ApplicationError

logger = logging.getLogger("taskhub")


class UnitOfWork(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


@asynccontextmanager
async def transaction_scope(
    uow: UnitOfWork, failure_message: str
) -> AsyncIterator[None]:
    """Commit on success and roll back application errors, failures, or cancellation."""
    try:
        yield
        await uow.commit()
    except ApplicationError:
        await uow.rollback()
        raise
    except BaseException:
        logger.exception("%s; rolling back", failure_message)
        await uow.rollback()
        raise
