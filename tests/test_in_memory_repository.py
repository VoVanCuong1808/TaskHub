"""Unit tests for the in-memory task repository."""

import subprocess
import sys
import unittest
from pathlib import Path
from uuid import uuid4

from app.models.enums import TaskPriority, TaskStatus
from app.models.task import Task
from app.repositories.task_repo import InMemoryTaskRepository


class InMemoryRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_list_filters_match_sql_store_contract(self) -> None:
        repository = InMemoryTaskRepository()
        project_id = uuid4()
        assignee_id = uuid4()
        for status, priority, assignee in (
            (TaskStatus.TODO, TaskPriority.HIGH, assignee_id),
            (TaskStatus.DONE, TaskPriority.HIGH, assignee_id),
            (TaskStatus.TODO, TaskPriority.LOW, None),
        ):
            await repository.add(
                Task(
                    title="filtered",
                    project_id=project_id,
                    created_by=uuid4(),
                    status=status,
                    priority=priority,
                    assignee_id=assignee,
                )
            )

        items, total = await repository.list(
            project_id=project_id,
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            assignee_id=assignee_id,
        )
        self.assertEqual((len(items), total), (1, 1))
        self.assertEqual(items[0].assignee_id, assignee_id)

    async def test_persistence_crud_has_no_authorization_or_transaction_logic(self) -> None:
        repository = InMemoryTaskRepository()
        project_id = uuid4()
        task = Task(
            title="unit test", project_id=project_id, created_by=uuid4()
        )

        await repository.add(task)
        items, total = await repository.list(
            project_id=project_id, offset=0, limit=1
        )
        self.assertEqual((items, total), ([task], 1))

        task = await repository.get_for_update(task.id)
        self.assertIsNotNone(task)
        task.title = "updated"
        await repository.save(task)
        saved = await repository.get(task.id)
        self.assertIsNotNone(saved)
        self.assertEqual(saved.title, "updated")
        await repository.delete(task.id)
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
