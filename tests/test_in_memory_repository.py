"""Unit tests for the in-memory task repository."""

import subprocess
import sys
import unittest
from pathlib import Path

from app.models.task import Task
from app.repositories.task_repo import InMemoryTaskRepository


class InMemoryRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_list_update_and_delete(self) -> None:
        repository = InMemoryTaskRepository()
        task = Task(title="unit test")

        await repository.add(task)
        items, total = await repository.list(offset=0, limit=1)
        self.assertEqual((items, total), ([task], 1))

        task.title = "updated"
        await repository.save(task)
        self.assertEqual((await repository.get(task.id)).title, "updated")
        self.assertTrue(await repository.delete(task.id))
        self.assertIsNone(await repository.get(task.id))


class DomainImportTests(unittest.TestCase):
    def test_domain_task_import_does_not_load_sqlalchemy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; import app.models.task; assert 'sqlalchemy' not in sys.modules",
            ],
            cwd=root,
            check=True,
        )
