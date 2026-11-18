"""Task-list cache unit and opt-in Redis integration tests."""

from __future__ import annotations

import ast
import asyncio
import os
import subprocess
import sys
import unittest
from pathlib import Path
from uuid import uuid4

from app.cache.redis_task_list_cache import DATA_TTL_SECONDS, RedisTaskListCache
from app.cache.task_list_snapshot import TaskListSnapshot
from app.models.enums import TaskPriority, TaskStatus
from app.models.task import Task
from app.services.task_list_cache import task_list_query_digest


class TaskListCacheSerializationTests(unittest.TestCase):
    def test_serialized_snapshot_round_trips_without_mutable_aliasing(self) -> None:
        original = Task(
            project_id=uuid4(),
            created_by=uuid4(),
            title="Vietnam Tích Hợp",
            description=None,
        )
        payload = TaskListSnapshot.from_tasks([original], 1).to_json()
        snapshot = TaskListSnapshot.from_json(payload)
        restored, total = snapshot.to_tasks()
        self.assertEqual(total, 1)
        self.assertEqual(restored[0].title, original.title)
        self.assertIsNone(restored[0].description)
        restored[0].title = "changed"
        self.assertEqual(
            TaskListSnapshot.from_json(payload).to_tasks()[0][0].title,
            original.title,
        )

    def test_malformed_payload_is_a_miss(self) -> None:
        for payload in ("{", "[]", '{"items": [], "total": -1}', '{"items": [null], "total": 1}'):
            with self.subTest(payload=payload):
                self.assertIsNone(TaskListSnapshot.from_json(payload))

    def test_application_cache_port_has_no_redis_or_http_schema_dependency(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source_path = root / "app/services/task_list_cache.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        forbidden = ("redis", "fastapi", "app.schemas", "app.cache")
        self.assertFalse(
            any(
                name == root or name.startswith(f"{root}.")
                for name in imported
                for root in forbidden
            )
        )

        script = """
import sys
import app.services.task_list_cache
assert not any(name == 'redis' or name.startswith('redis.') for name in sys.modules)
assert not any(name == 'fastapi' or name.startswith('fastapi.') for name in sys.modules)
assert not any(name == 'app.schemas' or name.startswith('app.schemas.') for name in sys.modules)
assert not any(name == 'app.cache' or name.startswith('app.cache.') for name in sys.modules)
"""
        subprocess.run([sys.executable, "-c", script], cwd=root, check=True)


class TaskListCacheAdapterValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_schema_valid_snapshot_for_another_project_is_a_miss(self) -> None:
        expected_project = uuid4()
        wrong_project = uuid4()
        task = Task(project_id=wrong_project, created_by=uuid4(), title="misrouted")
        same_project_task = Task(
            project_id=expected_project, created_by=uuid4(), title="same-project"
        )

        class Client:
            payload = TaskListSnapshot.from_tasks([task], 1).to_json()

            async def get(self, key):
                return self.payload

        cache = RedisTaskListCache(Client())
        self.assertIsNone(await cache.get(expected_project, "generation", "query"))
        cache._client.payload = TaskListSnapshot.from_tasks(
            [same_project_task], 1
        ).to_json()
        result = await cache.get(expected_project, "generation", "query")
        self.assertEqual((result[0][0].title, result[1]), ("same-project", 1))

    def test_query_digest_includes_every_filter_and_page_dimension(self) -> None:
        common = {
            "q": "hello",
            "status": TaskStatus.DONE,
            "priority": TaskPriority.HIGH,
            "assignee_id": uuid4(),
            "offset": 20,
            "limit": 20,
        }
        base = task_list_query_digest(**common)
        for name, value in (("q", "hello2"), ("status", None), ("priority", None), ("assignee_id", None), ("offset", 40), ("limit", 10)):
            changed = {**common, name: value}
            with self.subTest(dimension=name):
                self.assertNotEqual(base, task_list_query_digest(**changed))


@unittest.skipUnless(
    os.getenv("TASKHUB_TEST_REDIS_URL"),
    "set TASKHUB_TEST_REDIS_URL to run disposable Redis integration tests",
)
class RedisTaskListCacheIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        from redis.asyncio import Redis

        self.namespace = f"taskhub:test:{uuid4()}:task-list:v1"
        self.client = Redis.from_url(
            os.environ["TASKHUB_TEST_REDIS_URL"],
            socket_connect_timeout=0.5,
            socket_timeout=0.5,
            max_connections=4,
        )
        self.cache = RedisTaskListCache(self.client, namespace=self.namespace)
        self.project_id = uuid4()

    async def asyncTearDown(self) -> None:
        async for key in self.client.scan_iter(match=f"{self.namespace}:*"):
            await self.client.delete(key)
        await self.client.aclose()

    async def test_generation_cas_snapshot_ttl_and_old_token_rejection(self) -> None:
        generation = await self.cache.generation(self.project_id)
        other_project = uuid4()
        other_generation = await self.cache.generation(other_project)
        task = Task(project_id=self.project_id, created_by=uuid4(), title="Snapshot")
        self.assertTrue(
            await self.cache.set_if_current(
                self.project_id, generation, "query", [task], 1
            )
        )
        first, total = await self.cache.get(self.project_id, generation, "query")
        key = self.cache._data_key(self.project_id, generation, "query")
        before_hit = await self.client.pttl(key)
        self.assertGreater(before_hit, 0)
        self.assertLessEqual(before_hit, DATA_TTL_SECONDS * 1000)
        first[0].title = "mutated"
        second, again_total = await self.cache.get(self.project_id, generation, "query")
        after_hit = await self.client.pttl(key)
        self.assertLessEqual(after_hit, before_hit)
        self.assertEqual((second[0].title, total, again_total), ("Snapshot", 1, 1))
        self.assertIsNone(
            await self.cache.get(other_project, other_generation, "query")
        )

        await self.client.pexpire(key, 150)
        expiry_ttl = await self.client.pttl(key)
        self.assertIsNotNone(await self.cache.get(self.project_id, generation, "query"))
        self.assertLessEqual(await self.client.pttl(key), expiry_ttl)
        await asyncio.sleep(0.2)
        self.assertIsNone(await self.cache.get(self.project_id, generation, "query"))

        await self.cache.rotate(self.project_id)
        next_generation = await self.cache.generation(self.project_id)
        self.assertNotEqual(next_generation, generation)
        self.assertFalse(
            await self.cache.set_if_current(
                self.project_id, generation, "late-query", [task], 1
            )
        )
        self.assertIsNone(
            await self.cache.get(self.project_id, next_generation, "query")
        )

        await self.client.delete(self.cache._generation_key(self.project_id))
        recreated = await self.cache.generation(self.project_id)
        self.assertNotIn(recreated, {generation, next_generation})
        self.assertFalse(
            await self.cache.set_if_current(
                self.project_id, next_generation, "evicted-query", [task], 1
            )
        )

    async def test_malformed_redis_value_is_a_cache_miss(self) -> None:
        generation = await self.cache.generation(self.project_id)
        key = self.cache._data_key(self.project_id, generation, "bad")
        await self.client.set(key, "not-json", ex=DATA_TTL_SECONDS)
        self.assertIsNone(await self.cache.get(self.project_id, generation, "bad"))
        await self.client.set(key, b"\xff", ex=DATA_TTL_SECONDS)
        self.assertIsNone(await self.cache.get(self.project_id, generation, "bad"))
