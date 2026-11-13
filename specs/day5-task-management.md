# Day 5: Task Management

## Status, baseline, and source boundary

This specification targets branch `feat/day5-task-management` at
`429199a` (`origin/main`), after Day 4 Workspace Management was merged.

The original `pag1.png`-`pag4.png` requirements were recovered at
`C:/Users/ADMIN/Downloads/taskhub/pag1.png` through `pag4.png`. Feature 8 on
page 4 requires task filtering by status, priority, and assignee with page and
limit pagination. The source images confirm those requirements; repository
artifacts provide the existing API, schema, and compatibility constraints:

- the initial Day 2 migration and current SQLAlchemy model contain task
  assignment, priority, due date, project labels, task-label links, and task
  comments;
- the legacy-upgrade path explicitly preserves those fields and relationships;
- the Day 4 authorization specification explicitly deferred assignment,
  priority, due date, labels, and comments from the already delivered task CRUD;
- the current API implements authenticated, project-scoped CRUD only for
  `title`, `description`, and `status`.

Accordingly, Day 5 exposes the deferred task fields, labels, comments, and the
source-required task filters and pagination. It does not rebuild task CRUD or
authentication and does not infer attachments, watchers, subtasks, recurrence,
estimates, search, new workflow states, or project management.

## Existing behavior that must remain compatible

- Keep canonical `/api/v1/tasks` routes and the hidden `/tasks` alias.
- Keep Bearer access-token authentication, project/workspace visibility, hidden
  404 behavior, OWNER/EDITOR writes, VIEWER reads, archived-project read/write
  behavior, and the global ADMIN non-bypass rule.
- Keep the current task success codes: create 201, reads/updates 200, delete 204.
- Keep project-scoped task listing, the existing optional `status` filter,
  deterministic newest-first order, and shared `Page[T]` /
  `PaginationParams` (`page=1`, `limit=20`, `1..200`).
- Add optional `priority` and `assignee_id` task-list filters; combine them with
  `status` using AND semantics and the required `project_id` scope.
- Use one-based `page` plus `limit` on every public list route. Reject the
  removed public `offset` query parameter with 422; keep offset only inside
  service/repository interfaces.
- Keep existing title/description/status validation and partial-update
  semantics. Additive response fields are allowed; existing fields and paths
  must not be removed or renamed.

## In scope

1. Expose `priority`, `due_date`, and `assignee_id` on task create, update, and
   read contracts.
2. Manage labels within a project and attach/detach them from tasks in that same
   project.
3. Create, list, read, edit, and delete comments belonging to a task.
4. Extend the pure workspace permission policy for label and comment actions.
5. Refactor task persistence to the same service-owned Unit of Work boundary as
   Workspace Management: repositories execute SQL only; services own use cases,
   business rules, authorization orchestration, locking order, and transactions.

## API contract

All routes require the existing Bearer access token. The hidden `/tasks` alias
continues to mirror only the existing task CRUD routes; no hidden aliases are
added for label or comment routes.

### Tasks

Existing routes remain in place:

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/api/v1/tasks` | 201 `TaskRead` |
| `GET` | `/api/v1/tasks?project_id=...&status=...&priority=...&assignee_id=...` | 200 `Page[TaskRead]` |
| `GET` | `/api/v1/tasks/{task_id}` | 200 `TaskRead` |
| `PATCH` | `/api/v1/tasks/{task_id}` | 200 `TaskRead` |
| `DELETE` | `/api/v1/tasks/{task_id}` | 204, empty body |

`TaskCreate` adds these optional fields:

| Field | Type | Default / rule |
| --- | --- | --- |
| `priority` | `low \| medium \| high \| urgent` | `medium`; explicit null invalid |
| `due_date` | timezone-aware ISO 8601 datetime or null | null; normalize to UTC |
| `assignee_id` | UUID or null | null; must be an active user visible in the task workspace |

`TaskUpdate` adds the same fields. Omitted fields remain unchanged. Explicit
null clears `due_date` or `assignee_id`; explicit null is invalid for `priority`.
No rule forbids a past due date because no source requirement defines one.

`TaskRead` is additive and contains:

`id`, `project_id`, `title`, `description`, `status`, `priority`, `due_date`,
`assignee_id`, `created_by`, `created_at`, and `updated_at`.

Task listing requires `project_id` and accepts optional `status`, `priority`,
and `assignee_id` filters, combined with AND. `assignee_id` is an exact task
column match inside the authorized project query. It does not look up or
validate the user: unknown or outside-workspace UUIDs return an empty authorized
page, without disclosing user existence. The count query uses the same project
and filter predicates as the item query. Both `/api/v1/tasks` and the hidden
`/tasks` alias expose the same filters and pagination.

`PaginationParams` contains a one-based `page` (default 1) and `limit` (default
20, range 1–200). All public list endpoints use those
parameters and reject any supplied `offset` query parameter with 422, whether
or not `page` is also supplied. Page-derived offsets are bounded so the
effective offset stays within signed SQL `BIGINT` range. The shared
schema/helper calculates the normalized internal offset; repositories do not
implement pagination business rules. `Page[T]` remains `{items,total}`, with
`total` calculated before pagination.

Labels and comments are not embedded in `TaskRead`; their paginated endpoints
avoid unbounded task responses and duplicate pagination contracts. Day 5 does
not add due-date, text-search, sort, or label filters to task listing.

### Labels

Labels are project resources. Flat label routes match the existing flat task API
and avoid introducing project CRUD as a prerequisite.

| Method | Path | Role | Result |
| --- | --- | --- | --- |
| `POST` | `/api/v1/labels` | OWNER/EDITOR | 201 `LabelRead`; body is `project_id`, `name`, `color` |
| `GET` | `/api/v1/labels?project_id=...&page=...&limit=...` | OWNER/EDITOR/VIEWER | 200 `Page[LabelRead]` |
| `GET` | `/api/v1/labels/{label_id}` | OWNER/EDITOR/VIEWER | 200 `LabelRead` |
| `PATCH` | `/api/v1/labels/{label_id}` | OWNER/EDITOR | 200 `LabelRead`; partial `name` and/or `color` |
| `DELETE` | `/api/v1/labels/{label_id}` | OWNER/EDITOR | 204, empty body |
| `GET` | `/api/v1/tasks/{task_id}/labels` | OWNER/EDITOR/VIEWER | 200 `Page[LabelRead]` |
| `PUT` | `/api/v1/tasks/{task_id}/labels/{label_id}` | OWNER/EDITOR | 204; idempotently attach |
| `DELETE` | `/api/v1/tasks/{task_id}/labels/{label_id}` | OWNER/EDITOR | 204; detach an existing link |

`LabelCreate` requires `project_id`, a trimmed non-empty `name` of at most 100
characters, and a trimmed non-empty `color` of at most 32 characters.
`LabelUpdate` uses omission to mean unchanged and rejects explicit null. The
schema provides no unique-name or color-format constraint, so Day 5 permits
duplicate names and does not invent a hex-only color rule.

`LabelRead` contains `id`, `project_id`, `name`, `color`, `created_at`, and
`updated_at`. Label lists order by `created_at`, then `id`, both ascending, for a
stable project vocabulary. Task-label lists use the association `created_at`,
then `label_id`, ascending. `total` is calculated before pagination.

A label can attach only to a task in the same project. `PUT` on an existing link
is successful and does not create a second row. Detaching a nonexistent link
returns 404. Deleting a label relies on the existing cascade to delete its task
links, not its tasks.

### Comments

| Method | Path | Role | Result |
| --- | --- | --- | --- |
| `POST` | `/api/v1/tasks/{task_id}/comments` | OWNER/EDITOR | 201 `CommentRead`; body is `content` |
| `GET` | `/api/v1/tasks/{task_id}/comments?page=...&limit=...` | OWNER/EDITOR/VIEWER | 200 `Page[CommentRead]` |
| `GET` | `/api/v1/comments/{comment_id}` | OWNER/EDITOR/VIEWER | 200 `CommentRead` |
| `PATCH` | `/api/v1/comments/{comment_id}` | comment author with current OWNER/EDITOR task-write access | 200 `CommentRead` |
| `DELETE` | `/api/v1/comments/{comment_id}` | comment author with current OWNER/EDITOR task-write access | 204, empty body |

`CommentCreate` requires trimmed, non-empty `content`. `CommentUpdate` requires
the `content` field, applies the same validation, and rejects null. The database
uses `Text` and no source defines a maximum, so this slice does not invent one.
NUL characters are invalid at the API boundary.

`CommentRead` contains `id`, `task_id`, `author_id`, `content`, `created_at`, and
`updated_at`. The authenticated actor is always `author_id`; clients cannot
supply or change it. Lists order by `created_at`, then `id`, ascending and use
the shared pagination types. Day 5 does not add owner moderation of another
author's comment because no available requirement grants it; deleting the task
still cascades all its comments.

## Data and business rules

### Assignment

- A valid assignee is the workspace owner or an active user with an effective
  OWNER/EDITOR/VIEWER membership in the task's workspace. A legacy owner without
  a membership row remains valid.
- A stale OWNER membership belonging to a non-owner does not confer OWNER
  authority, but the user remains an effective VIEWER under the existing policy
  and can be assigned.
- A global ADMIN without workspace membership cannot be assigned merely because
  of the global role.
- An unknown, inactive, or out-of-workspace assignee is rejected with 422 and
  `{"detail":"Assignee must be an active workspace member"}`. The message does
  not disclose whether the user exists.
- Removing a workspace member does not rewrite historical task rows in Day 5.
  Existing `assignee_id` remains until explicitly cleared or the user is deleted;
  the existing user-delete FK behavior remains `SET NULL`.

### Priority and due date

- Reuse `TaskPriority`: `low`, `medium`, `high`, `urgent`; database enum values
  remain `LOW`, `MEDIUM`, `HIGH`, `URGENT` through SQLAlchemy's current mapping.
- Existing rows already have non-null `medium`; no backfill is required.
- Datetimes must be timezone-aware, are stored as `TIMESTAMPTZ`, and are emitted
  as UTC-aware values. Naive datetimes return 422.
- Priority and due date do not change authorization or workflow status.

### Labels

- A label belongs to exactly one project. A task-label link is valid only when
  `label.project_id == task.project_id`; the service enforces this invariant
  before persistence.
- Existing many-to-many primary key `(task_id, label_id)` remains authoritative.
- Labels may be renamed or recolored while attached. Moving a label between
  projects is not supported; `project_id` is immutable after creation.

### Comments

- A comment belongs to exactly one task and its author is immutable.
- Creating or mutating a comment is a write against the parent task's project;
  archived projects therefore return the existing 409 `Project is archived`.
- A comment author who has since lost task-write permission can still read the
  comment if visible but cannot edit or delete it.

## Authorization policy

Extend the existing pure `WorkspaceRole -> WorkspacePermission` mapping rather
than branching on roles in APIs or repositories.

| Permission | OWNER | EDITOR | VIEWER |
| --- | --- | --- | --- |
| `TASK_READ` | yes | yes | yes |
| `TASK_CREATE`, `TASK_UPDATE`, `TASK_DELETE` | yes | yes | no |
| `LABEL_READ`, `COMMENT_READ` | yes | yes | yes |
| `LABEL_CREATE`, `LABEL_UPDATE`, `LABEL_DELETE`, `TASK_LABEL_UPDATE`, `COMMENT_CREATE` | yes | yes | no |
| `COMMENT_UPDATE`, `COMMENT_DELETE` | yes, own comment only | yes, own comment only | no |

Task creator or assignee status never overrides workspace permissions. Comment
authorship is an additional restriction, not a substitute for current workspace
write permission. Global ADMIN still has no implicit workspace access.

## Layering and transaction contract

The implementation must preserve this dependency direction:

`API transport -> Service use case -> pure policy + Unit of Work -> SQL repositories`

- API modules validate HTTP input, resolve the principal, call one service use
  case, serialize output, and contain no SQL, transaction, or role logic.
- Services load facts through the UoW, call pure policies, enforce cross-row
  rules, mutate domain/entity state, and delimit each write transaction.
- Pure policy functions accept values/context objects and return/raise decisions;
  they import neither FastAPI nor SQLAlchemy and perform no I/O.
- Repository adapters contain SQL queries, row locks, flush/add/delete, and
  persistence mapping only. They do not authorize, choose HTTP/application
  errors, commit, or roll back.
- A request-scoped `TaskManagementUnitOfWork` owns the shared SQLAlchemy session,
  exposes the required task/project/workspace/member/user/label/comment stores,
  and is the only task-management component with `commit`/`rollback`.
- Replace `TaskRepository.commit/rollback`, repository authorization, and
  repository-raised visibility errors. Do not add a second transaction wrapper
  around the same session or let TaskService depend directly on FastAPI/Pydantic
  transport schemas.
- Read use cases do not commit and do not lock rows. Every write commits exactly
  once on success and rolls back on every application or unexpected exception.

## Concurrency and lock order

All writes that depend on current workspace authority use one transaction and a
single lock order compatible with Day 4:

1. lock the parent workspace row;
2. lock the actor membership row when it exists;
3. lock the parent project row;
4. lock the primary mutable resource (`task`, `label`, or `comment`);
5. lock secondary validation rows in deterministic UUID order (assignee
   membership/user, then label/link rows as applicable).

Consequences:

- A membership removal/role change or ownership change that wins the workspace
  lock is observed before a task-management write commits; revoked authority
  cannot be used after revocation commits.
- Task PATCH locks and reloads the task before applying the partial payload, so
  concurrent updates to distinct fields retain both changes rather than saving a
  stale full snapshot.
- Assignment validates the assignee under the same transaction. Concurrent
  member removal serializes on the workspace/membership locks.
- Comment edit/delete locks the comment, resolves its locked parent task/project,
  and checks the immutable author inside the same transaction.
- Label attach locks task and label before checking same-project membership and
  inserting the association. Concurrent duplicate PUTs are idempotent; use
  conflict-safe SQL or catch the unique race within the transaction.
- Locks for collections of UUID rows are acquired in sorted UUID order. Do not
  introduce an optimistic-version column in this slice.

## Error and precedence contract

Application errors use the existing `{"detail":"..."}` shape; request-schema
errors retain the current FastAPI 422 detail list.

1. Authentication is resolved before resource lookup: missing, invalid,
   expired, refresh-type, or inactive-user credentials return 401 plus
   `WWW-Authenticate: Bearer`.
2. A missing or invisible project/task/label/comment returns the corresponding
   concealed 404. Hidden and nonexistent IDs have the same response body.
3. A visible VIEWER attempting a write returns 403
   `Insufficient workspace role`.
4. A visible OWNER/EDITOR writing an archived project returns 409
   `Project is archived`.
5. A non-author attempting to edit/delete a visible comment returns 403
   `Comment can only be changed by its author`.
6. Invalid assignee or a cross-project task-label link returns 422 with the
   stable business detail described in this spec.

Additional stable details:

- missing label: 404 `Label not found`;
- missing comment: 404 `Comment not found`;
- missing task-label link on DELETE: 404 `Task label not found`;
- cross-project link: 422 `Label must belong to the task project`.

Database integrity mappings remain the final safety net, not the normal path for
business validation. No raw SQL/driver message is returned.

## Migration and compatibility contract

- No migration is expected. All required tables, columns, enums, foreign keys,
  cascade behavior, and basic indexes already exist at `429199a`.
- Do not edit historical migrations, reset data, or rewrite the legacy-upgrade
  utility. Existing tasks, labels, links, comments, assignees, priorities, and
  due dates must remain intact.
- Do not add a schema migration merely to implement service/repository/API
  behavior. If implementation discovers actual schema drift, stop and document
  the exact mismatch before proposing an additive reversible revision.
- No new dependency is required.

## Test contract

Unit tests must cover pure policy and service behavior without PostgreSQL:

- priority/due-date/assignee payload defaults, null/omission behavior, enum and
  timezone validation;
- assignee owner/member/legacy-owner/inactive/outsider/global-ADMIN cases;
- label same-project invariant, idempotent attach, missing detach, immutable
  project, and exact role matrix;
- comment author assignment, author-only mutation, role loss, archived project,
  validation, ordering, and pagination;
- service transaction ownership: one commit on success, rollback on application
  and unexpected errors, no commit for reads;
- pure policies have no FastAPI/SQLAlchemy imports, and repositories contain no
  policy or commit/rollback behavior.

API/PostgreSQL integration tests must cover:

- all new routes reject bad authentication with 401 and Bearer challenge;
- OWNER/EDITOR success, VIEWER read-only 403, outsider and global ADMIN hidden
  404, legacy owner behavior, and archived read/409 write behavior;
- task create/read/update persistence for priority, UTC due date, assignment,
  unassignment, and additive `created_by` response;
- project-scoped labels, stable `Page[LabelRead]`, attach/detach, duplicate
  concurrent attach, cross-project rejection, and label-delete link cascade;
- task-scoped comments, stable `Page[CommentRead]`, author-only updates/deletes,
  task-delete cascade, and hidden parent resources;
- task list and every new list calculate `total` on exactly the authorized,
  filtered parent scope before pagination;
- membership removal/role change and ownership change serialize with each new
  write; concurrent partial task updates preserve distinct fields;
- migration upgrade and legacy conversion preserve populated priority,
  due-date, assignee, label/link, and comment rows.

Existing auth, task authorization/CRUD, workspace management, pagination,
integrity mapping, browser client, and migration tests remain green. Day 5
implementation should run focused unit tests first, then the PostgreSQL suite
only against the explicitly configured disposable `taskhub_test` database.

## Acceptance checklist

- [ ] Existing task CRUD/auth paths, statuses, hidden alias, 404 concealment,
      archived behavior, and shared pagination remain compatible.
- [ ] Task listing supports AND-combined status/priority/assignee filters,
      scoped totals, one-based page/limit, and rejects public offset with 422.
- [ ] Task create/update/read expose and persist priority, aware-UTC due date,
      assignee, and creator according to the data contract.
- [ ] Assignment accepts only active workspace-visible users, including the
      legacy owner rule, and does not grant authorization.
- [ ] Project labels support paginated CRUD and same-project task attach/detach.
- [ ] Task comments support paginated create/read and author-only edit/delete.
- [ ] OWNER/EDITOR/VIEWER and global ADMIN behavior matches the permission table.
- [ ] API is transport-only; services own use cases and transaction boundaries;
      pure policy owns decisions; repositories contain SQL/persistence only;
      the UoW alone commits or rolls back.
- [ ] Write checks and mutations share one transaction and the documented lock
      order; revocation, partial-update, and duplicate-attach races are tested.
- [ ] Existing schema and data are reused with no migration or new dependency.
- [ ] Unit, API, PostgreSQL, concurrency, cascade, and migration-preservation
      tests satisfy the test contract without weakening existing coverage.
- [ ] README/OpenAPI examples describe additive task fields, supported task
      filters/page pagination, and label/comment endpoints without claiming
      unsupported filters or features.

## Explicitly out of scope

- Reimplementing authentication, workspace management, project CRUD, or the
  already delivered basic task CRUD/authorization contract.
- Attachments, notifications, watchers, mentions, subtasks, dependencies,
  recurrence, time estimates/tracking, activity feeds, bulk operations, text
  search, filters beyond task status/priority/assignee, custom priorities or
  statuses, or workflow transitions.
- Assigning users outside the workspace, assignee-based permission overrides,
  global ADMIN bypass, owner moderation of another author's comment, label moves
  between projects, or label uniqueness/color-format rules.
- New nested project-task CRUD routes, removal of `/tasks`, websocket/background
  work, optimistic versions, permission tables, or a generic repository
  framework.

## Source confirmation

The recovered images confirm task filter feature 8: filter by status, priority,
and assignee, and paginate using page plus limit. The concrete query contract
above also preserves the application’s existing project scope, hidden alias,
shared `Page[T]` response, and authorization behavior. The public API now
accepts page/limit only; offset remains an internal service/repository value.

## First work package for `day5_impl`

Start with the architectural seam, not endpoints:

1. Add failing unit tests for the extended task value/null/timezone/assignee
   contract and for service-owned commit/rollback.
2. Introduce the request-scoped Task Management UoW and SQL-only store protocols;
   move current task authorization/resource-not-found decisions from
   `TaskRepository` into `TaskService` plus pure policy while preserving every
   existing task test and HTTP response.
3. Extend the pure domain task and task schemas/repository mapping with
   `priority`, `due_date`, `assignee_id`, and `created_by`; implement assignment
   validation and concurrent partial-update locking.
4. Stop after focused non-DB tests are green and review this seam before adding
   labels and comments as later work packages.

Do not combine the first package with label/comment endpoints: the UoW refactor
is the shared foundation and should be reviewable without unrelated API surface.
