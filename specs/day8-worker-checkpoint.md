# Day 8 worker checkpoint — WP1 Projects

Date: 2026-11-20. Branch: `feat/day8-project-completion`, based on merged
PR10 (`ff14cc7`). WP1 implementation is ready for coordinator review. This
checkpoint records worker status only; `specs/day8-project-completion.md` remains
coordinator-owned and unchanged.

## Implemented

- Added project create/list/read/update/delete routes and archive/restore through
  the existing status field, with ProjectCreate/Update/Read schemas, shared
  pagination and explicit HTTP error documentation.
- Added project permissions to workspace RBAC, a ProjectService/UoW, SQL-only
  ProjectRepository, and routed task persistence through that shared repository.
- Preserved write locking order: project observation, workspace `FOR SHARE`,
  actor membership `FOR SHARE`, then refreshed project `FOR UPDATE` plus parent
  recheck. Workspace/project authorization facts now load through one narrow
  ProjectService helper.
- Project list and total use one ordered SQL statement. Successful update/delete
  commit before task-list cache generation rotation; commit, persistence, and
  cache failure paths have focused service coverage.
- Added HTTP/service tests and moved project PostgreSQL/Redis cases into
  `tests/test_project_postgres.py`, separate from the broad PostgreSQL suite.
  Gated database tests cover permission matrix, pagination/cascade/archive/cache,
  and real ProjectService archive racing with a task create.
- Added refreshed-locked-row partial-update and changed-parent regressions.

## Focused checks

- `python -m unittest tests.test_project_api tests.test_project_service
  tests.test_authorization tests.test_task_authorization tests.test_task_service
  tests.test_workspace_service tests.test_pagination`: **56 passed** in 3.258s.
- `unittest` discovery loads exactly **3** tests from
  `tests.test_project_postgres`, all owned by `ProjectPostgreSQLTests`; total
  repository discovery is 146 tests. The baseline `PostgreSQLTests` class is
  accessed through a module alias, so it is not exposed as a second TestCase in
  the project test module.
- `ruff check app tests`: passed.
- `git diff --check`: passed (Git emitted only normal LF-to-CRLF notices).
- `py_compile` on touched application and project test modules: passed.
- No DB, Redis, Docker, migration, `.env`, or pytest operations were run. The
  coordinator owns the gated PostgreSQL/Redis suite and independent review.

## Review follow-up

Read the independent report at
`C:/Users/ADMIN/AppData/Local/Temp/taskhub-day8-review.md`. Added injected
repository-update failure rollback/no-rotation coverage, retained commit-failure
coverage, and exercised post-commit cache failure for both update and delete.
Partial updates now explicitly prove that values on a freshly returned locked
row are preserved; reparented locked rows are hidden and rolled back. Real
PostgreSQL archive-vs-task-create service interleaving is in the focused gated
module for coordinator execution.

## Boundaries

No email, Docker, README-wide completion work, commit, push, merge, `.env` edit,
or spec edit was performed. Await coordinator review before WP2/WP3.

## WP2 assignment notifications — worker handoff

- Added frozen, slotted `TaskAssignmentEvent` and application-side
  `TaskAssignmentNotifier` protocol in `app/services/task_assignment.py`.
- TaskService captures task ID/title and the already validated, share-locked
  assignee email inside the current transaction. It schedules only after the
  transaction context commits: assigned create and changed-to-non-null update
  notify; unassigned create, unchanged assignment, unassignment, authorization
  failure and failed commit do not.
- Added FastAPI `BackgroundTasks` adapter and DI wiring. Jobs receive only the
  sender and immutable primitive event, not ORM rows or request sessions.
- Added stdlib `EmailMessage`/`smtplib` transport using `asyncio.to_thread`,
  configured socket timeout, constant subject and verified STARTTLS context.
  Background send and scheduling failures log only a static message and exception
  class, without credentials or message contents; committed tasks remain success.
- Settings support optional SMTP host, bounded port/timeout, validated sender,
  paired optional username/SecretStr password, and STARTTLS. Default sender is
  `no-reply@example.com`. With no `TASKHUB_SMTP_HOST`, notifications remain
  disabled; `.env.example`, Compose/Mailpit and README configuration are left
  for coordinator-owned WP3. No root `.env` was read or changed.
- Focused checks:
  `python -m unittest -q tests.test_task_assignment_notifications
  tests.test_task_service tests.test_auth_security.SettingsTests`: **38 passed**
  in2.945s. Ruff, `py_compile` on changed application/test modules, and
  `git diff --check` passed.
- No database, Redis, Docker, migration, SMTP network, pytest, or Git publication
  action was run. Coordinator owns Mailpit capture and final integration runs.
- Worker has handed back implementation ownership after WP2. Do not begin WP3 or
  make further source edits unless coordinator requests a concrete correction.

## WP3 worker source-ready handoff — 2026-11-21

- Fixed the blank `TASKHUB_SMTP_PASSWORD=` case: exact empty dotenv values map to
  `None`; nonempty passwords retain all leading/trailing whitespace. The new
  temporary-dotenv regression was red before the validator and is green after it.
- README now documents the full Compose startup, host-development alternative,
  persistent secret generation without printing, port override, project/task
  API workflow, assignment capture in Mailpit, search/page/cache and the
  in-process best-effort delivery boundary. Added SMTP settings and static-check
  commands. The actual root `.env` was not read or edited.
- Full-stack Dockerfile, `.dockerignore` and Compose configuration are present;
  coordinator had already validated Compose config. Mailpit health uses its
  image-provided `/mailpit readyz` command. Source and Compose are now frozen for
  coordinator-owned build/smoke work.
- Checks completed before handoff: mypy passed with no issues in73 app files;
  Ruff passed; `uv lock --check` passed after allowing uv cache access; focused
  non-DB suite passed72 tests in4.115s, including WP1/assignment/config tests.
  The blank-password regression separately passed3 SMTP settings tests.
- Coordinator t19 owns Docker Desktop startup, image build, full Postgres/Redis
  test run in t1v, and real HTTP/Mailpit probe. Worker did not run Docker, DB,
  migrations or a duplicate database suite. No further source edits until a
  concrete review correction is sent.
