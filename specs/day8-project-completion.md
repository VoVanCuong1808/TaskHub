# Final mini-project completion — 2026-11-20

## Source, baseline and deliverable

Coordinator re-read all four original images at
`C:/Users/ADMIN/Downloads/taskhub/pag1.png` through `pag4.png`.
Pages 1/2 group days 3–7 into core features, then Day 8 requires architecture,
DRY/naming review, performance review, Ruff and mypy without errors, and complete
README/setup. Page 3 requires Project CRUD/archive (feature 4). Page 4 additionally
requires assignment email in background (10), resource RBAC (11), Bearer/error
Swagger/ReDoc docs (12), and one Compose startup for app/DB/Redis (13).

PR10 is MERGED as ff14cc72697aaf23c66997d4a0b7c7c3c72aaa70.
The clean new branch `feat/day8-project-completion` starts at origin/main ff14cc7,
which contains reviewed commit 10af545. No uncommitted user work was present.
Existing auth/user/workspace/task/label/comment/search/filter/page/cache behavior
must remain compatible. No UI/frontend, unrelated feature framework, or real
external-recipient email delivery is requested. Do not commit/push/merge until
the final implementation has been reviewed and user requests publication.

## Remaining work and boundaries

1. Project create/list/read/update/delete and archive/unarchive, including RBAC,
   SQL locks/cascades, validation, errors and HTTP docs.
2. Background email when a task gets a new assignee, using SMTP and a local
   capture mailbox for real delivery verification. No email sent before commit
   or after rollback. No SMTP error may undo or fail an already committed task.
3. Multi-stage Dockerfile and full-stack Compose including migration/bootstrap,
   app/DB/Redis health checks and local SMTP capture; preserve existing local app
   volume/data and separate disposable test services. No destructive volume reset.
4. Meaningful application mypy configuration/checks, Ruff, complete API error
   docs and README, real integration/end-to-end workflow/performance checks.

Architecture remains API HTTP-only -> application use cases/authorization and
transaction orchestration -> SQL-only repositories. Pure policy has no I/O.
Reuse shared trimmed text, named constants, pagination/Page and existing lock
order. Services own commit/rollback via UoW. Keep cache port, Redis adapter and
snapshot codec separated. No generic repository, notification or queue framework.
Use unittest; never add/install pytest.

## Project contract (WP1)

- POST/GET `/api/v1/workspaces/{workspace_id}/projects` create/list scoped projects.
  POST 201, GET Page[ProjectRead]. Reuse page>=1/limit1..200 and reject offset.
- GET/PATCH/DELETE `/api/v1/projects/{project_id}` return 200/200/204.
  Existing flat task/label/comment routes and hidden `/tasks` alias remain.
- Create: name trimmed, non-empty <=NAME_MAX_LENGTH; description optional/null,
  <=PROJECT_DESCRIPTION_MAX_LENGTH; status defaults active. Reject NUL and
  unknown fields. Response includes id/workspace_id/name/description/status/
  created_at/updated_at. Workspace is immutable.
- Partial update: only name/description/status; omission preserves value;
  description:null clears; explicit null name/status and invalid status ->422.
  status active/archived implements archive and restore without a new endpoint.
- OWNER/EDITOR can create/update/archive/restore/delete, VIEWER can read/list.
  Preserve actual workspace owner authority, stale OWNER membership treated as
  viewer, global ADMIN non-bypass and hidden 404 for outsider/missing parent.
  Visible but forbidden write ->403. Archived project reads remain allowed;
  project metadata/status update and delete remain allowed. Existing task/label/
  comment writes under archived project retain their existing409 behavior.
- Add project permission constants to the existing pure RBAC map. Reuse or move
  the existing task project SQL store into a single coherent project repository,
  with a minimal matching application/UoW seam; avoid duplicate project SQL stores.
  Do not create an unrelated generic repository framework.
- For writes, observe project only to discover parent, then lock workspace and
  actor membership FOR SHARE before mutable project FOR UPDATE; reload/recheck
  project after locks. Parent/member updates/deletes already take conflicting
  locks. Creation locks parent/member before insert. Preserve lock order and do
  not upgrade shared parent locks to exclusive locks late in a task transaction.
- List/count must use one statement and deterministic created_at/id descending
  ordering, including out-of-range pages. Project deletion uses DB cascade for
  tasks/labels/task-labels/comments. Cache is invalidated only after committed
  project update/delete; parent existence/auth must still precede task cache reads.
  Workspace cascade deletion remains protected by fresh authorization/parent
  existence and cache TTL; do not add an unbounded Redis key scan.
- Tests: values/nulls/immutability, owner/editor/viewer/admin/outsider matrix,
  archive/restore/task write behavior, partial update locking, page total/order,
  deletion cascade and warm-cache protection, concurrent task writes vs project
  archive/delete or role revocation. Unit/API and real Postgres regressions.

## Assignment email contract (WP2, after WP1 review)

- Notify a non-null assignee on create and when assignee changes to a different
  non-null user. No duplicate email for same-assignee PATCH, unassignment,
  unassigned create, unauthorized operation, failed commit or rollback.
- Resolve/validate assignee and capture immutable primitive event data while
  inside the existing transaction/locks; schedule only after commit. Do not retain
  request AsyncSession or ORM objects in background jobs.
- Application notification port/event is HTTP/SMTP independent. FastAPI
  BackgroundTasks scheduling belongs to an adapter/DI; SMTP transport is separate
  and uses stdlib EmailMessage/smtplib with asyncio.to_thread and bounded timeout.
  Keep task service use-case orchestration; no SMTP or FastAPI import there.
- SMTP settings validate at startup; credentials use SecretStr; local Mailpit
  captures messages without relaying to external users. Use a constant safe
  subject (no unsanitized title/header injection) and plain-text task details.
  Log failures without credentials or full email bodies; committed writes stay
  successful. Document in-process background delivery as best-effort across
  crashes; do not claim durable/exactly-once delivery or add Celery/outbox.
- Verify scheduling order/immutable snapshots, unchanged/no assignee, commit
  failure, transport failure, event-loop safety and real local SMTP capture.

## Docker, docs and final verification (WP3)

- Build an unprivileged runtime image from a multi-stage Python3.12 dependency
  build using the lock file; runtime excludes dev deps, `.env`, Git and caches.
  Compose uses internal DB/Redis/SMTP hostnames, loopback host-published ports,
  durable named Postgres volume, healthchecks and a migration prerequisite.
- Retain existing `compose.local.yaml` application DB volume at5433; full-stack
  startup must not collide with the existing host server8000 or user services.
  Inspect ports/state before launch and choose/document a free app port if needed.
  Reuse actual JWT secret privately, never echo it or stage `.env`.
- Local SMTP capture is allowed; real external-recipient messages are not.
- Add mypy as a dev tool only if absent. Check application code with meaningful
  types; do not silence all errors or change business behavior to satisfy typing.
  Run Ruff, mypy, unittest, diff/secret checks and Docker/HTTP/SMTP/Redis checks.
- Swagger/ReDoc cover new and existing endpoints with Bearer and error shapes.
  README must show account -> workspace -> project -> task -> labels/comments ->
  search/page/cache -> assignment mail flow and repeatable Compose startup.

## Coordination/checkpoint

User explicitly requests Herdr pane coordination and same-session auto compaction.
Installed old `herdr`0.9.5 points at a stopped legacy socket. Running desktop uses
`herdr-core`0.1.21 and `herdr-app` CLI instead; both installed manuals were read,
and the active core/window were inspected without restarting either. Existing
TaskHub terminals are finished; active visible terminals belong to another
project. Create a clearly named TaskHub completion worker surface, keep current
user focus, and never control/close unrelated agents.

One implementation writer on the shared checkout. Coordinator owns this spec,
independent review, disposable services and full validation. Work packages are
sequential: WP1 projects -> review -> WP2 mail -> review -> WP3 packaging/quality
-> final complete workflow. Worker checkpoints before /compact; keep same session
and surface. Existing test containers taskhub-day5-db/taskhub-day6-redis are
stopped and need restart/verification before testing. No application-data deletes
or real SMTP delivery. Final completion evidence must be recorded here.

### Coordinator checkpoint — baseline

- New visible Herdr terminal `t1c`, TaskHub / Day8 Completion, resumes the same
  implementation session in the current TaskHub directory (not its old recorded
  Davel-Trace directory). WP1 delivered and worker observed working.
- Disposable `taskhub-day5-db` verified: database `taskhub_test` exists;
  `taskhub-day6-redis` at loopback6380 returns PONG. No application DB modified.
- Baseline full unittest: 131 tests, no skips, OK, 49.938s (terminal `t1f`).
- Background email design reference: https://fastapi.tiangolo.com/tutorial/background-tasks/
  and https://fastapi.tiangolo.com/advanced/advanced-dependencies/ — dependency
  injection can schedule tasks, but jobs must receive their own primitive data.
- Local SMTP capture reference: https://mailpit.axllent.org/docs/install/docker/
  documents SMTP1025 and web8025; publish only to loopback in our Compose.

### Correct pane mapping confirmed with user screenshot

Live screen comparison identifies coordinator as `t19` and the user's adjacent
old Task6 coordinator as `t1b` (not Task5 panes). Initial inherited hc caller ID
`t15` and launch-directory metadata were stale. Subsequent hc commands explicitly
set process-local `HC_TERMINAL_ID=t19`; do not touch unrelated t14/t15 sessions.
The user-selected adjacent `t1b` now receives read-only review work; review output
goes only to TEMP/taskhub-day8-review.md. `t1c` stays sole implementation writer in
TaskHub / Day8 Completion. Both keep same sessions and checkpoint before compact.
Mailpit image axllent/mailpit:v1.32.0 downloaded successfully, not started yet.
Baseline teardown removes the disposable test schema; migrate taskhub_test before
standalone performance probes (an initial no-schema probe failed without writes).

### Disposable performance review

After explicit Alembic upgrade on taskhub_test only, a transaction inserted 5,000
synthetic tasks and EXPLAIN ANALYZE measured the current single-statement count
plus ordered page shape: page20 3.250ms, status/priority filters3.276ms, literal
title/description search8.019ms (15 matching rows). This is a local query probe,
not a production throughput claim. Fixture transaction rolled back; no application
data touched. Existing indexed project scope, bounded pagination and Redis reuse
are sufficient at this sample size; no speculative full-text/search framework.
Independent TEMP scripts: taskhub-final-perf.py and taskhub-final-smoke.py.

### WP1 review checkpoint

- Adjacent t1b read-only review found no confirmed production defect; requested
  transaction/cache-failure and refreshed-row evidence. Worker added these and
  consolidated workspace/member context lookup in ProjectService.
- Real Postgres+Redis project CRUD/RBAC/page/archive/cascade and warm-cache
  deletion regressions passed 2 tests in10.873s before the test-file move.
- Coordinator caught unittest's collection of an imported TestCase: initial
  focused-module count49; fixed by module import, independently verified count3.
  Project DB cases now live in tests/test_project_postgres.py, not the monolith.
- Full WP1 suite terminal t1n: **146 tests, no skips, OK in52.559s** with real
  disposable Postgres/Redis. WP1 independently approved; WP2 dispatched to t1c.
- Worker checkpoint: specs/day8-worker-checkpoint.md, 56 focused non-DB tests pass.

Mypy was absent; coordinator installed it into the project virtualenv with uv pip
only (no source/lock changes). WP3 must add the dev dependency to pyproject/lock
and meaningful configuration. Initial app check with check_untyped_defs runs in
t1q; report TEMP/taskhub-mypy-initial.log. Do not hide errors wholesale.

### Resume 2026-11-21 — actual adjacent pane ownership

User's new screenshot identifies t19 coordinator and t1b adjacent implementation
session. t1c is now a shell, not the active worker. Coordinator explicitly handed
SOLE implementation ownership to t1b for remaining WP3; t19 stays read-only on
application/tests/docs until that handoff returns. Prompt delivered and worker
observed Working; no unrelated panes controlled. Continue same-session compaction.
Current drafted Docker/Compose passed config --quiet, migrations copy corrected
to alembic/. Mypy was fixed to zero errors across73app files and dev lock updated.
Still require fresh final full tests, Docker build/start, real Mailpit HTTP probe,
README and empty SMTP password regression. No publication authorized for Day8.

### Final coordinator verification — 2026-11-21

- Correct adjacent worker t1b completed WP3 and froze source; checkpoint records
  72 focused tests, Ruff, mypy73files and uv lock --check passed.
- Coordinator independently checked Ruff/mypy and diff; full unittest t1v passed
  **156 tests, zero skips, 73.463s** on dedicated taskhub_test/Redis6380.
- Docker Desktop Linux engine was stopped; coordinator started it hidden, then
  restarted only the two disposable test containers. Existing application DB
  volume5433 and unrelated services/data were preserved.
- Full `docker compose -f compose.yaml up --build -d --wait` (t1w) exited0:
  app/Postgres/Redis/Mailpit healthy, migration exited0. Separate new durable
  taskhub-stack_postgres_data volume; no volume deletion or reset.
- Real HTTP/Mailpit probe t1y PASS: auth/RBAC, project CRUD/archive/restore,
  task/label/comment cascades, combined search/filter/page, warm-cache mutation
  and membership revocation, exactly one captured assignment email for the tested
  unchanged-assignee scenario, Swagger/ReDoc. No external email relay configured.
- Runtime uid10001, .env absent, mypy absent. Real Redis had5 cache keys after
  probe. Signing key scan across tracked/unignored files found zero matches;
  secret itself was never printed. README-only final wording change needs no
  runtime rebuild (README is not copied into runtime stage).
- Stack remains running: API/docs http://127.0.0.1:8000/docs,
  ReDoc http://127.0.0.1:8000/redoc, Mailpit http://127.0.0.1:8025.
- Assignment delivery is in-process best-effort, not durable/exactly-once.
  No commit, push, PR creation or merge performed for this Day8 branch.

### User-approved shutdown and publication — 2026-11-21

User accepted the result and explicitly requested stopping activity and pushing.
Stopped all taskhub-stack services and the two dedicated test containers using
stop only; volumes/data retained. Worker implementation was already frozen/idle.
Publish this completed branch; no merge or unrelated service shutdown requested.
