"""Settings, SMTP transport and FastAPI adapter tests for assignment mail."""

from __future__ import annotations

import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.deps import get_task_assignment_notifier
from app.notifications.background import (
    BackgroundTaskAssignmentNotifier,
)
from app.notifications.smtp import (
    TASK_ASSIGNMENT_SUBJECT,
    SMTPTaskAssignmentSender,
)
from app.services.task_assignment import TaskAssignmentEvent, TaskAssignmentNotifier


def assignment_event(title: str = "Build weekly report") -> TaskAssignmentEvent:
    return TaskAssignmentEvent(
        task_id=uuid4(), task_title=title, recipient_email="assigned@example.test"
    )


class SMTPSettingsTests(unittest.TestCase):
    def test_smtp_configuration_is_optional_and_has_a_valid_default_sender(self) -> None:
        settings = Settings(_env_file=None, redis_url=None)
        self.assertIsNone(settings.smtp_host)
        self.assertEqual(str(settings.smtp_from_email), "no-reply@example.com")
        self.assertEqual(settings.smtp_timeout_seconds, 5)

        configured = Settings(
            _env_file=None,
            redis_url=None,
            smtp_host="  mailpit  ",
            smtp_username=" delivery ",
            smtp_password="SMTP_FAKE_PASSWORD",
            smtp_starttls=True,
            smtp_timeout_seconds=30,
        )
        self.assertEqual(configured.smtp_host, "mailpit")
        self.assertEqual(configured.smtp_username, "delivery")
        self.assertIsInstance(configured.smtp_password, SecretStr)
        self.assertEqual(configured.smtp_timeout_seconds, 30)

    def test_database_password_is_secret_and_round_trips_url_reserved_characters(self) -> None:
        raw_password = "DB_FAKE@PASSWORD/#%"
        settings = Settings(
            _env_file=None,
            redis_url=None,
            database_url="postgresql+asyncpg://postgres@localhost:5432/taskhub",
            database_password=raw_password,
        )

        self.assertEqual(make_url(settings.resolved_database_url).password, raw_password)
        self.assertNotIn(raw_password, settings.resolved_database_url)
        self.assertNotIn(raw_password, repr(settings))
        alembic_config = Config()
        alembic_config.set_main_option(
            "sqlalchemy.url", settings.resolved_database_url.replace("%", "%%")
        )
        self.assertEqual(
            make_url(alembic_config.get_main_option("sqlalchemy.url")).password,
            raw_password,
        )
        self.assertIsNone(Settings(_env_file=None, database_password="").database_password)

    def test_blank_dotenv_password_disables_auth_without_trimming_passwords(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dotenv = Path(directory) / ".env"
            dotenv.write_text(
                "TASKHUB_SMTP_HOST=mailpit\nTASKHUB_SMTP_PASSWORD=\n",
                encoding="utf-8",
            )
            settings = Settings(_env_file=dotenv, _env_file_encoding="utf-8")

        self.assertIsNone(settings.smtp_password)
        exact_secret = "  SMTP_FAKE_PASSWORD  "
        configured = Settings(
            _env_file=None,
            redis_url=None,
            smtp_host="mailpit",
            smtp_username="delivery",
            smtp_password=exact_secret,
            smtp_starttls=True,
        )
        self.assertEqual(
            configured.smtp_password.get_secret_value(), exact_secret
        )

    def test_smtp_configuration_rejects_incomplete_or_unbounded_values_safely(self) -> None:
        invalid = (
            {"smtp_username": "delivery"},
            {"smtp_password": "SMTP_FAKE_PASSWORD"},
            {"smtp_host": "mailpit", "smtp_username": "delivery"},
            {"smtp_host": "mailpit", "smtp_username": "delivery", "smtp_password": "SMTP_FAKE_PASSWORD", "smtp_starttls": False},
            {"smtp_timeout_seconds": 0},
            {"smtp_timeout_seconds": 30.1},
            {"smtp_port": 65536},
            {"smtp_host": "smtp://mailpit"},
            {"smtp_from_email": "not-an-email"},
        )
        for fields in invalid:
            with self.subTest(fields=fields):
                with self.assertRaises(ValidationError) as raised:
                    Settings(_env_file=None, redis_url=None, **fields)
                self.assertNotIn("SMTP_FAKE_PASSWORD", str(raised.exception))


class SMTPTransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_send_uses_worker_thread_secure_starttls_and_constant_subject(self) -> None:
        from email.message import EmailMessage
        from ssl import CERT_REQUIRED
        from unittest.mock import patch

        event = assignment_event("Build\r\nSubject: forged")
        main_thread = threading.get_ident()
        sent: dict[str, object] = {}

        class SMTPDouble:
            def __init__(self, host: str, port: int, *, timeout: float) -> None:
                sent["connection"] = (host, port, timeout)
                sent["thread"] = threading.get_ident()

            def __enter__(self):
                return self

            def __exit__(self, *_args) -> None:
                return None

            def starttls(self, *, context) -> None:
                sent["tls_context"] = context

            def login(self, username: str, password: str) -> None:
                sent["login"] = (username, password)

            def send_message(self, message: EmailMessage) -> None:
                sent["message"] = message

        sender = SMTPTaskAssignmentSender(
            host="mailpit",
            port=1025,
            from_email="no-reply@example.com",
            username="delivery",
            password=SecretStr("SMTP_FAKE_PASSWORD"),
            starttls=True,
            timeout_seconds=4,
        )
        with patch("app.notifications.smtp.smtplib.SMTP", SMTPDouble):
            await sender.send(event)

        self.assertEqual(sent["connection"], ("mailpit", 1025, 4))
        self.assertNotEqual(sent["thread"], main_thread)
        tls_context = sent["tls_context"]
        self.assertEqual(tls_context.verify_mode, CERT_REQUIRED)
        self.assertTrue(tls_context.check_hostname)
        self.assertEqual(sent["login"], ("delivery", "SMTP_FAKE_PASSWORD"))
        message = sent["message"]
        self.assertEqual(message["Subject"], TASK_ASSIGNMENT_SUBJECT)
        self.assertEqual(message["To"], event.recipient_email)
        self.assertIn("Subject: forged", message.get_content())
        self.assertEqual(len([value for value in message.values() if value == "forged"]), 0)


class BackgroundAssignmentAdapterTests(unittest.TestCase):
    def test_fastapi_dependency_schedules_immutable_event_and_contains_delivery_failure(self) -> None:
        from unittest.mock import patch

        event = assignment_event()
        delivered: list[TaskAssignmentEvent] = []

        class Sender:
            async def send(self, snapshot: TaskAssignmentEvent) -> None:
                delivered.append(snapshot)

        app = FastAPI()
        app.state.settings = Settings(
            _env_file=None, redis_url=None, smtp_host="mailpit"
        )

        @app.post("/assignment")
        async def schedule_assignment(
            notifier: Annotated[
                TaskAssignmentNotifier | None,
                Depends(get_task_assignment_notifier),
            ],
        ) -> dict[str, bool]:
            self.assertIsNotNone(notifier)
            await notifier.schedule(event)
            return {"scheduled": True}

        with patch(
            "app.core.deps.SMTPTaskAssignmentSender", return_value=Sender()
        ), TestClient(app) as client:
            response = client.post("/assignment")

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json(), {"scheduled": True})
        self.assertEqual(delivered, [event])

    def test_background_delivery_failure_does_not_log_secret_or_message_body(self) -> None:
        from fastapi import BackgroundTasks

        event = assignment_event("PRIVATE_BODY")

        class BrokenSender:
            async def send(self, _snapshot: TaskAssignmentEvent) -> None:
                raise RuntimeError("SMTP_FAKE_PASSWORD PRIVATE_BODY")

        tasks = BackgroundTasks()
        notifier = BackgroundTaskAssignmentNotifier(tasks, BrokenSender())
        with self.assertLogs("taskhub", level="WARNING") as logs:
            asyncio.run(notifier.schedule(event))
            asyncio.run(tasks())

        self.assertTrue(any("RuntimeError" in line for line in logs.output))
        self.assertTrue(any(str(event.task_id) in line for line in logs.output))
        self.assertFalse(
            any("SMTP_FAKE_PASSWORD" in line or "PRIVATE_BODY" in line for line in logs.output)
        )
