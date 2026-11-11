# Day 4: Task Authorization

## Purpose and baseline

Day 4 adds authorization to the task API already built in Day 3. The baseline is commit `5041574` (Day 3), with the browser auth client and its flow test restored from `0035e56`. This specification is limited to the first authorization slice: task access governed by a user's workspace membership and the task's project/workspace parent chain.

The assignment screenshots (`pag1.png`–`pag4.png`) call for Bearer authentication, resource ownership, and ADMIN/OWNER/EDITOR/VIEWER authorization. The current code supplies users, workspaces, workspace memberships, projects, tasks, their role/status enums, auth dependencies, and task CRUD. Task routes are currently public; the task database repository still relies on seeded default project/user IDs. Day 4 must close those gaps without rebuilding the broader application described in the assignment.

## Scope

### Authentication

- Require a valid access-token Bearer credential on every task endpoint: create, list, read-one, update, and delete, at both `/api/v1/tasks` and the existing hidden `/tasks` alias.
- Resolve the principal through the existing `get_current_user` dependency. Do not accept a refresh token, cookie-only identity, user ID, or role supplied by the caller as task authorization.
- Missing, malformed, expired, wrong-type, or inactive-user credentials return the existing authentication response: HTTP 401, JSON `{"detail": "..."}`, and `WWW-Authenticate: Bearer`.
- Registration continues to assign `UserRole.MEMBER`; users cannot grant themselves ADMIN or a workspace role through auth/profile APIs.

### Workspace and project authorization

- A task is authorized through `Task.project_id → Project.workspace_id → Workspace`.
- A caller may see a project or its tasks only if they own that workspace or have a `WorkspaceMember` row for that workspace. A project that does not exist and a project inaccessible to the caller are both concealed with HTTP 404.
- Workspace ownership is recognized from `Workspace.owner_id`, even if a legacy workspace has no matching OWNER membership row. This does not require a migration to duplicate owner rows. An explicit owner field is authoritative if a redundant membership row is missing or stale.
- A non-owner's effective workspace role comes only from the matching `WorkspaceMember` row. The global `UserRole.ADMIN` is not a workspace membership and does not bypass this boundary. Workspace and project administration are not added in this slice.
- `OWNER` and `EDITOR` can create, read, update, and delete tasks in an accessible project. `VIEWER` can read and list, but cannot create, update, or delete. A known member with insufficient role receives HTTP 403. Task creator or assignee status does not grant a role override; permissions are determined by workspace role.
- Reads of archived projects remain allowed. Task creation and mutation in an archived project return HTTP 409 with `{"detail":"Project is archived"}`. No archive operation is introduced.

## Endpoint and response contract

Keep the current flat task routes to avoid breaking the Day 3 public API. Add the project scope explicitly as described below; nested `/projects/{project_id}/tasks` routes are not part of this slice.

| Method and path | Authorization | Contract |
| --- | --- | --- |
| `POST /api/v1/tasks` | OWNER or EDITOR in the target project workspace | Require `project_id` in the JSON body. Create with the authenticated user's ID as `created_by`; return 201 and the task representation. |
| `GET /api/v1/tasks` | Any workspace member or workspace owner | Require `project_id` query parameter. Return only tasks in that project, with the existing `status`, `offset`, and `limit` filters and `{items,total}` pagination shape. `total` counts only the authorized project result set. |
| `GET /api/v1/tasks/{task_id}` | Any workspace member or workspace owner | Return 200 and the task representation. |
| `PATCH /api/v1/tasks/{task_id}` | OWNER or EDITOR in the task's project workspace | Preserve current partial-update behavior and fields. Return 200 and the task representation. |
| `DELETE /api/v1/tasks/{task_id}` | OWNER or EDITOR in the task's project workspace | Return 204 with no body. |

The `/tasks` alias has identical behavior and remains hidden from OpenAPI as it is today. Task representations add `project_id` so clients can identify the resource scope. Task creation adds required `project_id`; task listing adds required `project_id`. Existing fields and validation remain unchanged: create/update continue to support only the current title, description, and status fields; read continues to include the current task fields plus `project_id`. Do not add assignment, priority, due-date, label, or comment request behavior in this change.

### Error precedence and shape

- Use the existing JSON `detail` error shape. Keep existing validation errors as HTTP 422 and preserve successful status codes and response shapes unless specified above.
- Return HTTP 404 for both a missing task/project and a task/project outside the caller's workspace visibility. This applies to read, update, delete, and project-scoped listing/create where the target project cannot be seen. Do not reveal whether a hidden identifier exists.
- Return HTTP 403 only when the caller is authenticated, is known to be an owner/member who can see the workspace resource, but their role does not permit the requested action. In this slice this is a VIEWER attempting a write to a visible project/task.
- Return HTTP 409 for writes against an archived, visible project. Preserve existing integrity error mapping for conflicts and invalid references; do not turn authorization failures into database errors.
- Authentication is checked before resource lookup: unauthenticated requests always receive 401, even when the supplied resource ID is missing or hidden.

## Data, migrations, and compatibility

- Use existing `User`, `Workspace`, `WorkspaceMember`, `Project`, and `Task` fields and relationships. `WorkspaceRole` is OWNER/EDITOR/VIEWER; `UserRole` is ADMIN/MEMBER. No role enum or ownership field is renamed or reinterpreted.
- Remove task repository dependence on `DEFAULT_PROJECT_ID` and `DEFAULT_USER_ID`. The project comes from the request and `created_by` comes from the authenticated principal. No task may silently be created under the seed project or as the seed user.
- Continue using existing task `project_id` and `created_by` foreign keys. Do not delete, reassign, or rewrite existing users, memberships, projects, or tasks to make authorization pass. Existing tasks become visible according to their existing project's workspace owner/membership rows.
- No schema migration is expected for this scope. If implementation requires schema changes, use an additive, reversible migration and preserve all existing rows, foreign keys, indexes, enum values, and the Day 2 legacy-upgrade path. Do not edit or replace historical migrations, reset the database, or add a permissive default project/user to satisfy new non-null request context.
- Existing clients must begin sending a Bearer access token and a `project_id` for create/list. Item routes keep their existing paths. Update README examples and OpenAPI descriptions to show the required Bearer header and project scope.

## Transaction and concurrency rules

- For every write, perform visibility/role checks and the task/project mutation in one database transaction. Roll back on authorization, validation, or persistence failure; do not leave a partially changed task.
- For update/delete, load and lock the target task using the existing row-locking approach, then resolve its project/workspace and authorize against that locked resource context before changing it. Never authorize from caller-supplied project IDs for an existing task.
- For create/list, constrain repository queries by the requested project and the caller's workspace visibility; apply the same scope to both page rows and total count. Create the task only after confirming an accessible, writable, active project.
- A membership/ownership check and its corresponding write must use a consistent transaction snapshot. Where membership revocation or ownership transfer can occur concurrently, serialize the authorization decision with the relevant membership/workspace row lock (or an equivalent database-supported isolation strategy) so a write cannot commit using a role that was revoked before it committed. Use a consistent lock order across affected rows to avoid deadlocks.
- Keep current `SELECT ... FOR UPDATE` semantics for concurrent task updates. Concurrent updates to different fields must retain both updates; deletes and updates must not operate on stale task state. Do not add optimistic version columns in this slice.

## Browser auth client and test restored from Day 3

Restore `examples/auth-client.js` and `examples/auth-client.test.mjs` from commit `0035e56` as part of Day 4. The Day 3 follow-up commit `5041574` deliberately deferred these files; they are part of the Day 4 deliverable, not optional cleanup.

- Preserve the source client's API: `createAuthClient({baseUrl, storage, fetchImpl})`, login/logout, authenticated request, and refresh behavior.
- Persist only the short-lived access token under `taskhub_access_token`; never persist or expose the refresh token. Refresh remains cookie-based with `credentials: "include"`.
- Authenticated requests attach `Authorization: Bearer <access token>`, refresh and retry once after an API 401, and clear local access state after refresh failure or logout. Keep same-origin path validation and the existing serialized/single-flight refresh behavior.
- Restore and retain the client flow test coverage from `0035e56`, then extend it to assert that task calls carry Bearer credentials and the required `project_id` scope and that inaccessible task responses surface as 404 while role denials surface as 403. Do not weaken existing refresh, logout, header-preservation, or origin-validation assertions.
- Do not broaden this into cross-tab token synchronization; README already documents that the access token is held in one tab's local storage and that refresh has a cross-tab race.

## Acceptance tests

The Day 4 change is accepted when automated tests cover all of the following:

1. Each task endpoint and alias rejects absent, invalid, expired, refresh-type, and inactive-user credentials with 401 and the Bearer challenge; valid access tokens identify the expected user.
2. An owner can list, create, read, update, and delete tasks in their workspace, including a legacy workspace whose `owner_id` has no OWNER membership row.
3. An EDITOR member can perform task CRUD; a VIEWER can list/read but receives 403 for create/update/delete. A creator or assignee who is only a viewer still receives 403.
4. A user with no membership cannot list tasks, create in the project, or read/update/delete a task in that project. Those cases return 404, as do nonexistent project/task IDs. Responses do not disclose resource existence or return hidden task rows/counts.
5. A member of one workspace cannot access another workspace's project/task, including when guessing IDs. An ADMIN without membership receives the same concealed 404.
6. Project-scoped list results and `total` exclude other projects, including for mixed workspace data and pagination/status filters.
7. Task create records the authenticated actor as `created_by`, uses the requested project, and cannot fall back to seeded IDs. Missing/invalid `project_id` follows the 422/404 contract; archived project writes return 409 while archived reads work.
8. Existing task field validation, partial updates, 201/200/204 success codes, and 422 validation shape remain intact. Database FK/integrity failures keep their established mapping.
9. Concurrent task updates preserve distinct field changes. A concurrent membership/ownership revocation cannot authorize a write after revocation commits; transactions roll back on failed authorization.
10. Existing database rows survive startup and migration with their relationships intact; no destructive migration or seed-based backfill is required.
11. The restored browser client test retains all `0035e56` refresh/logout/origin tests and verifies Bearer task calls and the 404/403 authorization outcomes.

## Explicitly out of scope

- Workspace or project CRUD, workspace invitations, member addition/removal, role changes, ownership transfer, and ADMIN workspace override.
- New nested project-task routes or removal/renaming of `/api/v1/tasks` and `/tasks`.
- Assigning tasks to users, changing priority/due date, labels, comments, attachments, notifications, cache/background jobs, or additional task workflow rules.
- Cross-tab browser auth synchronization, refresh-token storage in JavaScript, and redesign of the existing auth endpoints/session model.
- Adding global policy/authorization frameworks, optimistic version columns, or unrelated schema cleanups.

## Open decisions

These decisions are intentionally deferred because they are not needed for the first authorization slice:

1. Whether to add nested `/projects/{project_id}/tasks` routes in a later API version while retaining the flat routes.
2. Whether workspace owner and membership rows should eventually be normalized so an owner always has a corresponding OWNER membership row.
3. Whether ADMIN should gain an explicit support/administrative workspace override, with audited behavior and tests.
4. Whether task creator/assignee should later receive permissions distinct from their workspace role.
5. Whether membership management, ownership transfer, and project archive/unarchive endpoints should be implemented in a later day, including their role matrices.
6. Whether browser access-token storage should move from local storage to a different client-side strategy and how to coordinate refresh across tabs.
