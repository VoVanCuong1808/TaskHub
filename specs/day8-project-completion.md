# Final mini-project completion — 2026-11-20

## Source, baseline and deliverable

Requirements originate from the four original images at
`C:/Users/ADMIN/Downloads/taskhub/pag1.png` through `pag4.png`.
Pages 1/2 group days 3–7 into core features, then Day 8 requires architecture,
DRY/naming review, performance review, Ruff and mypy without errors, and complete
README/setup. Page 3 requires Project CRUD/archive (feature 4). Page 4 additionally
requires assignment email in background (10), resource RBAC (11), Bearer/error
Swagger/ReDoc docs (12), and one Compose startup for app/DB/Redis (13).

Baseline: merged PR10, ff14cc72697aaf23c66997d4a0b7c7c3c72aaa70,
which contains reviewed commit 10af545.
Existing auth/user/workspace/task/label/comment/search/filter/page/cache behavior
must remain compatible. No UI/frontend, unrelated feature framework, or real
external-recipient email delivery is requested.

## Scope and boundaries

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

## Project contract

- POST/GET `/api/v1/workspaces/{workspace_id}/projects` create/list scoped projects.
  POST 201, GET Page[ProjectRead]. Reuse page>=1/limit1..200 and reject offset.
  Missing workspaces and non-members map to WorkspaceNotFound on these nested
  routes; flat project routes continue hiding inaccessible projects.
- GET/PATCH/DELETE `/api/v1/projects/{project_id}` return 200/200/204.
  Existing flat task/label/comment routes and hidden `/tasks` alias remain.
- Create: name trimmed, non-empty <=NAME_MAX_LENGTH; description optional/null,
  <=PROJECT_DESCRIPTION_MAX_LENGTH; projects always start active and create
  rejects a supplied status. Reject NUL and unknown fields. Response includes
  id/workspace_id/name/description/status/
  created_at/updated_at. Workspace is immutable.
- Partial update: only name/description/status; omission preserves value;
  description:null clears; explicit null name/status and invalid status ->422.
  status active/archived implements archive and restore without a new endpoint.
- OWNER/EDITOR can create/update/archive/restore; only OWNER can permanently
  delete a project because deletion cascades to its tasks, labels and comments.
  VIEWER can read/list.
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

## Assignment email contract

- Notify a non-null assignee on create and when assignee changes to a different
  non-null user, except when the actor assigns the task to themselves. No
  duplicate email for same-assignee PATCH, unassignment,
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
- SMTP credentials require STARTTLS. Delivery/scheduling failure logs include
  task ID and exception type only, never recipient, body or credentials.
- Verify scheduling order/immutable snapshots, unchanged/no assignee, commit
  failure, transport failure, event-loop safety and real local SMTP capture.

## Docker, docs and final verification

- Build an unprivileged runtime image from a multi-stage Python3.12 dependency
  build using the lock file; runtime excludes dev deps, `.env`, Git and caches.
  Compose uses internal DB/Redis/SMTP hostnames, loopback host-published ports,
  durable named Postgres volume, healthchecks and a migration prerequisite.
- Compose requires a private `TASKHUB_POSTGRES_PASSWORD`; application settings
  receive it separately as `SecretStr` and safely build the encoded SQLAlchemy
  URL. The password initializes new volumes only and does not rotate a password
  in existing database data.
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
