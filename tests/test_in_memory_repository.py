"""Unit tests for the in-memory task repository."""

import subprocess
import sys
import unittest
from pathlib import Path
from uuid import uuid4

from app.core.exceptions import TaskNotFoundError
from app.models.task import Task
from app.repositories.task_repo import InMemoryTaskRepository
from app.schemas.task import TaskUpdate
from app.services.task_service import TaskService


class InMemoryRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_list_update_and_delete(self) -> None:
        repository = InMemoryTaskRepository()
        task = Task(title="unit test")
        project_id = uuid4()
        user_id = uuid4()

        await repository.add(task, project_id=project_id, user_id=user_id)
        items, total = await repository.list(
            project_id=project_id, user_id=user_id, offset=0, limit=1
        )
        self.assertEqual((items, total), ([task], 1))

        task.title = "updated"
        await repository.save(task)
        self.assertEqual(
            (await repository.get(task.id, user_id=user_id)).title, "updated"
        )
        self.assertTrue(await repository.delete(task.id, user_id=user_id))
        self.assertIsNone(await repository.get(task.id, user_id=user_id))

        with self.assertRaises(TaskNotFoundError):
            await TaskService(repository).get(task.id, user_id)
        with self.assertRaises(TaskNotFoundError):
            await TaskService(repository).update(
                task.id, TaskUpdate(title="missing"), user_id
            )


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
