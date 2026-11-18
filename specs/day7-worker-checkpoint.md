# Day 7 worker checkpoint — 2026-11-18

Worker remains in the original shared checkout and pane `w2:pE` on
`feat/day6-search-filter-pagination-caching`. All Day 6 changes are preserved.
The Day 7 spec remains coordinator-owned and unedited by the worker. No commit,
push, or PR was created.

## Repairs completed

- Split task-list caching by responsibility. `app/services/task_list_cache.py`
  contains only the application port and stable query digest;
  `app/cache/redis_task_list_cache.py` owns Redis/Lua operations; and
  `app/cache/task_list_snapshot.py` defines an HTTP-independent, validated v1
  snapshot representation. The application port has a static import test and a
  clean-subprocess check banning transitive Redis, FastAPI, HTTP-schema, and cache
  adapter imports. The adapter rejects validly-shaped snapshots for another
  project and tests same-project round-trip.
- `TaskRepository.list` now returns page rows and filtered total from one SQL
  statement, preserves a correct total for empty/out-of-range pages, and applies
  final outer ordering by `created_at DESC, id DESC`.
- Added `tests/test_task_repository.py`, which was run red before the repository
  change: observed calls were `scalars`, `scalar`, not one `execute`. Coordinator
  independently ran the actual PostgreSQL concurrency test against the prior
  two-query code and observed its expected single assertion failure: 2 page items
  paired with total 1. The new gated PostgreSQL test deletes a matching row after
  the reader's SELECT is buffered but before it returns, then checks coherent
  rows/total, tied-timestamp ID ordering across pages, out-of-range totals after
  delete, and totals/order after a filter-changing status update.
- Redis URL settings now accept `redis://` or `rediss://`, optional credentials,
  and an optional numeric database path. Query strings, fragments, whitespace,
  invalid hosts/ports, and non-numeric database paths fail validation so URL
  parameters cannot override bounded client timeouts. `hide_input_in_errors=True`
  prevents credential disclosure in validation tracebacks. README configuration
  and application structure are updated.

## Worker verification

- Focused non-DB unittest run: 11 tests passed, covering the one-statement unit
  contract, cache port import direction, snapshot/project validation, Redis URL
  validation, unavailable async Redis fallback, authorization-before-cache,
  in-flight CAS, and post-commit invalidation.
- After the credential-redaction change: its focused Settings test passed (1 test).
- `ruff check app tests`, `py_compile` on touched Python files, and
  `git diff --check` passed. CRLF conversion notices from Git are informational.
- Worker did not run PostgreSQL/Redis integration or Docker tests; coordinator owns
  the green PostgreSQL check and full suite. No final DB result is claimed here.

## Post-compact final config fix

- Added a credential-redaction regression for an NFKC-invalid Unicode hostname.
  It first failed because `urlsplit` exposed the raw netloc (including `FAKEPW`)
  in the Pydantic error.
- Moved `urlsplit`, `.port`, and `.hostname` access into one `ValueError` guard
  that raises only the generic Redis URL validation message with suppressed cause.
- `tests.test_auth_security.SettingsTests`: 5 passed; focused Ruff passed.
- Coordinator reports the independent combined PostgreSQL+Redis suite passed 128
  tests with no skips in 59.495s. Worker ran no database tests.
- `git diff --check` passed using a per-command safe-directory override; no global
  Git configuration was changed. Git printed informational LF-to-CRLF notices.

## Handoff state

Code and focused checks are complete. Coordinator's full-suite green result is
recorded above. Implementation is frozen; no commit, push, or PR was created.
