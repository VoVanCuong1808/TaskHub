"""FastAPI background-task adapter for assignment notifications."""

from __future__ import annotations

import logging
from typing import Protocol

from fastapi import BackgroundTasks

from app.services.task_assignment import TaskAssignmentEvent

logger = logging.getLogger("taskhub")


class TaskAssignmentSender(Protocol):
    async def send(self, event: TaskAssignmentEvent) -> None: ...


async def _deliver_safely(
    sender: TaskAssignmentSender, event: TaskAssignmentEvent
) -> None:
    try:
        await sender.send(event)
    except Exception as exc:  # noqa: BLE001 - a committed task must survive mail errors
        logger.warning("Task assignment email delivery failed (%s)", type(exc).__name__)


class BackgroundTaskAssignmentNotifier:
    def __init__(
        self, background_tasks: BackgroundTasks, sender: TaskAssignmentSender
    ) -> None:
        self._background_tasks = background_tasks
        self._sender = sender

    async def schedule(self, event: TaskAssignmentEvent) -> None:
        self._background_tasks.add_task(_deliver_safely, self._sender, event)
