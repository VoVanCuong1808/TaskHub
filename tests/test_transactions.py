"""Shared application transaction scope behavior."""

import asyncio
import unittest

from app.core.exceptions import ApplicationError
from app.services.transaction import transaction_scope


class FakeUnitOfWork:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class TransactionScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_commits_once_without_rollback(self) -> None:
        uow = FakeUnitOfWork()
        async with transaction_scope(uow, "Project transaction failed"):
            pass
        self.assertEqual((uow.commits, uow.rollbacks), (1, 0))

    async def test_application_error_rolls_back_without_failure_log(self) -> None:
        uow = FakeUnitOfWork()
        with self.assertRaises(ApplicationError):
            async with transaction_scope(uow, "Workspace transaction failed"):
                raise ApplicationError("expected domain failure")
        self.assertEqual((uow.commits, uow.rollbacks), (0, 1))

    async def test_cancellation_logs_caller_context_and_rolls_back(self) -> None:
        uow = FakeUnitOfWork()
        with self.assertLogs("taskhub", level="ERROR") as logs, self.assertRaises(
            asyncio.CancelledError
        ):
            async with transaction_scope(uow, "Task transaction failed"):
                raise asyncio.CancelledError
        self.assertIn("Task transaction failed; rolling back", logs.output[0])
        self.assertEqual((uow.commits, uow.rollbacks), (0, 1))

    async def test_commit_failure_rolls_back_and_keeps_caller_context(self) -> None:
        uow = FakeUnitOfWork()

        async def fail_commit() -> None:
            raise RuntimeError("commit failed")

        uow.commit = fail_commit
        with self.assertLogs("taskhub", level="ERROR") as logs, self.assertRaisesRegex(
            RuntimeError, "commit failed"
        ):
            async with transaction_scope(uow, "Project transaction failed"):
                pass
        self.assertIn("Project transaction failed; rolling back", logs.output[0])
        self.assertEqual(uow.rollbacks, 1)
