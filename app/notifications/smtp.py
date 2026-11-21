"""Bounded stdlib SMTP transport for task assignment messages."""

from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage

from pydantic import SecretStr

from app.services.task_assignment import TaskAssignmentEvent

TASK_ASSIGNMENT_SUBJECT = "You were assigned a TaskHub task"


class SMTPTaskAssignmentSender:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        from_email: str,
        username: str | None,
        password: SecretStr | None,
        starttls: bool,
        timeout_seconds: float,
    ) -> None:
        self._host = host
        self._port = port
        self._from_email = from_email
        self._username = username
        self._password = password
        self._starttls = starttls
        self._timeout_seconds = timeout_seconds

    async def send(self, event: TaskAssignmentEvent) -> None:
        await asyncio.to_thread(self._send_sync, event)

    def _send_sync(self, event: TaskAssignmentEvent) -> None:
        message = EmailMessage()
        message["From"] = self._from_email
        message["To"] = event.recipient_email
        message["Subject"] = TASK_ASSIGNMENT_SUBJECT
        message.set_content(
            "You have been assigned to a TaskHub task.\n\n"
            f"Task: {event.task_title}\n"
            f"Task ID: {event.task_id}\n"
        )

        with smtplib.SMTP(
            self._host, self._port, timeout=self._timeout_seconds
        ) as client:
            if self._starttls:
                client.starttls(context=ssl.create_default_context())
            if self._username is not None and self._password is not None:
                client.login(self._username, self._password.get_secret_value())
            client.send_message(message)
