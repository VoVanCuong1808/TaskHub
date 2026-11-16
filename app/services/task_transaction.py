"""Shared service-side transaction scope for Task Management use cases."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.core.exceptions import ApplicationError
from app.services.task_uow import TaskManagementUnitOfWork

logger = logging.getLogger("taskhub")


@asynccontextmanager
async def task_transaction(uow: TaskManagementUnitOfWork) -> AsyncIterator[None]:
    try:
        yield
        await uow.commit()
    except ApplicationError:
        await uow.rollback()
        raise
    except BaseException:
        logger.exception("Task transaction failed; rolling back")
        await uow.rollback()
        raise
