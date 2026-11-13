# Day 4: Workspace Management

This specification covers Workspace Management based on the sample-app
requirements in `pag1.png`–`pag4.png` and merged authorization baseline
`431dc00`. The earlier Task Authorization work is recorded as a historical
Day 3 follow-up in [day4-authorization.md](day4-authorization.md).

## Scope

- Require the existing authenticated Bearer principal for every endpoint.
- Provide workspace create/list/get/update/delete. Creation assigns the caller
  as `owner_id` and creates the corresponding `OWNER` membership atomically.
- Owners and members can read visible workspace details and member lists.
  Workspace lists contain only workspaces owned by or joined by the caller.
- Owners can invite an existing active user by email as `EDITOR` or `VIEWER`,
  change a member's role, and remove a member. Email delivery and pending invites
  are out of scope.
- `OWNER` is reserved for the workspace owner: it cannot be assigned as a
  membership role, changed, or removed. Editors/viewers attempting mutations
  receive 403. Missing workspaces and requests by non-members are concealed with
  404. Unknown/inactive invitees or missing memberships return 404; duplicate
  memberships and owner membership changes return 409. Invalid payloads return
  422.
- `Workspace.owner_id` is the sole source of effective OWNER authority. A
  stale OWNER membership for a different user remains visible with VIEWER
  permissions; normal EDITOR/VIEWER memberships retain their roles.
- Reuse the static `WorkspaceRole` → `WorkspacePermission` policy. Global
  `UserRole.ADMIN` does not bypass membership. No custom roles, permission
  tables, invitation table, migration, or ownership transfer.

## Persistence and concurrency

- The service applies a pure role policy to repository-loaded workspace and
  membership data. The repository only queries, locks, and persists. Writes lock
  the workspace first, then actor and target membership rows, and persist in the
  same service-owned unit of work. Failed writes roll back. This order serializes
  role changes and removals with task authorization, which also locks membership
  before committing a task write. Reads do not lock rows.
- Workspace and member list endpoints accept `offset` and `limit` and return
  `{items, total}`, where `total` counts the complete visible/authorized set.
- Preserve the existing schema and task authorization behavior.

## Acceptance

- API/PostgreSQL tests cover unauthenticated 401s, owner/editor/viewer behavior,
  cross-workspace hidden 404s (including global ADMIN), 403 visible mutations,
  404 missing/inactive invitees and memberships, 409 duplicate/owner conflicts,
  workspace CRUD, membership CRUD, and owner membership creation.
- Existing Task authorization, membership-revocation locking, ownership
  serialization, migration compatibility, and browser auth tests remain green.
