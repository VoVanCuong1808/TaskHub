# PR10 worker checkpoint — 2026-11-19

Worker changes for the three requested review comments are complete and frozen.
The coordinator-owned `specs/pr10-review-fixes.md` was not edited. No DB/Docker
run, `.env` access, commit, or push was performed.

## Changes

- `Settings.redis_url` now uses native `RedisDsn | None`; only the blank-string
  before-validator remains. Frontend-origin validation is unchanged. README and
  tests follow Pydantic's native defaults, query options, and Unicode handling.
- Redis lifespan wiring parses the native DSN, then reapplies named app-owned
  socket timeout, retry count, and pool limit constants before constructing an
  owned `ConnectionPool` via `Redis.from_pool`. A no-network lifespan test proves
  query options cannot raise timeouts or pool size and checks pool ownership.
- Cache read, fill, and post-commit invalidation warnings include exception
  tracebacks. Tests verify exception type/message/traceback, DB fallback, and
  successful committed writes. Cached item/snapshot validation hides input; tests
  cover malformed JSON and invalid task-to-snapshot conversion without exposing
  a private sentinel.
- Search length, Redis timeouts/pool/retries, and task-list TTLs are centralized
  in `app/core/constants.py`.

## Verification

- Focused non-DB unittest run: 48 passed, covering auth/settings, task service,
  cache serialization/validation and the no-network Redis pool wiring check.
- `ruff check app tests` passed; `git diff --check` passed. Git emitted only
  informational LF-to-CRLF notices.
- Coordinator owns the full PostgreSQL+Redis integration run and final
  review/push. Worker did not run those integration tests.
- Herdr pane inspection/coordination was blocked by the elevated server's
  `PermissionDenied` boundary. Per the Herdr skill, worker did not restart or
  bypass it and did not interact with the unrelated pane.

No further source edits are planned.
