"""Task repository query consistency contracts."""

import unittest
from uuid import uuid4

from app.repositories.task_database import TaskRepository


class TaskListStatementTests(unittest.IsolatedAsyncioTestCase):
    async def test_page_and_total_are_read_by_one_statement_even_when_page_is_empty(self) -> None:
        class Result:
            def all(self):
                return [(None, 17)]

        class Session:
            def __init__(self) -> None:
                self.calls: list[str] = []

            async def execute(self, statement):
                self.calls.append("execute")
                return Result()

            async def scalars(self, statement):
                self.calls.append("scalars")
                return []

            async def scalar(self, statement):
                self.calls.append("scalar")
                return 17

        session = Session()
        items, total = await TaskRepository(session).list(
            project_id=uuid4(), offset=100, limit=20
        )

        self.assertEqual((items, total), ([], 17))
        self.assertEqual(session.calls, ["execute"])
