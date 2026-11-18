"""Redis implementation of the application task-list cache port."""

from __future__ import annotations

import secrets
from typing import TYPE_CHECKING
from uuid import UUID

from app.cache.task_list_snapshot import TaskListSnapshot
from app.models.task import Task

if TYPE_CHECKING:
    from redis.asyncio import Redis

DATA_TTL_SECONDS = 60
GENERATION_TTL_SECONDS = 120

_ENSURE_GENERATION = """
local current = redis.call('GET', KEYS[1])
if not current then
  redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2], 'NX')
  current = redis.call('GET', KEYS[1])
end
return current
"""
_SET_IF_CURRENT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
  return 1
end
return 0
"""
_ROTATE_GENERATION = "redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2]); return 1"


class RedisTaskListCache:
    def __init__(self, client: Redis, *, namespace: str = "taskhub:task-list:v1") -> None:
        self._client = client
        self._namespace = namespace.rstrip(":")

    def _generation_key(self, project_id: UUID) -> str:
        return f"{self._namespace}:project:{project_id}:generation"

    def _data_key(self, project_id: UUID, generation: str, digest: str) -> str:
        return f"{self._namespace}:project:{project_id}:generation:{generation}:query:{digest}"

    async def generation(self, project_id: UUID) -> str:
        token = secrets.token_urlsafe(24)
        result = await self._client.eval(
            _ENSURE_GENERATION,
            1,
            self._generation_key(project_id),
            token,
            GENERATION_TTL_SECONDS,
        )
        if not result:
            raise RuntimeError("Redis returned no project generation")
        return result.decode() if isinstance(result, bytes) else str(result)

    async def get(
        self, project_id: UUID, generation: str, query_digest: str
    ) -> tuple[list[Task], int] | None:
        payload = await self._client.get(
            self._data_key(project_id, generation, query_digest)
        )
        if payload is None:
            return None
        snapshot = TaskListSnapshot.from_json(payload)
        if snapshot is None or any(
            item.project_id != project_id for item in snapshot.items
        ):
            return None
        return snapshot.to_tasks()

    async def set_if_current(
        self,
        project_id: UUID,
        generation: str,
        query_digest: str,
        items: list[Task],
        total: int,
    ) -> bool:
        payload = TaskListSnapshot.from_tasks(items, total).to_json()
        return bool(
            await self._client.eval(
                _SET_IF_CURRENT,
                2,
                self._generation_key(project_id),
                self._data_key(project_id, generation, query_digest),
                generation,
                payload,
                DATA_TTL_SECONDS,
            )
        )

    async def rotate(self, project_id: UUID) -> None:
        await self._client.eval(
            _ROTATE_GENERATION,
            1,
            self._generation_key(project_id),
            secrets.token_urlsafe(24),
            GENERATION_TTL_SECONDS,
        )
