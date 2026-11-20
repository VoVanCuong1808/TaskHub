# Day 6: Searching, filtering, pagination, caching

## Verified baseline and sources

PR9 is MERGED into main at e308605 (2026-11-16 inspection). This branch,
`feat/day6-search-filter-pagination-caching`, starts at origin/main e308605,
which contains f55e909 and 661b006; no stacked PR dependency remains.
The checkout was clean before this specification. No AGENTS.md was found in
the repository or inspected parent directories.

The coordinator personally inspected all four original images at
`C:/Users/ADMIN/Downloads/taskhub/pag1.png` through `pag4.png`:

- Page 1 calls for layered architecture, asynchronous persistence, RBAC and Redis.
- Page 2 discusses configuration, optional Docker/background work and final review.
- Page 3 features 6/7 require project labels and task comments, already delivered
  in Day 5, alongside task assignment/priority/due date.
- Page 4 feature 8 requires status/priority/assignee AND filtering and page+limit.
  Feature 9 requires Redis caching of project task lists and invalidation on change.
  Its nested endpoint list is explicitly a reference. Feature 10 email and project
  CRUD are outside this task. Existing flat routes remain canonical.

Search is explicitly requested by the user, but the images do not define text
search semantics. The narrow contract below is a deliberate product choice.

## API, data, authorization and errors

- Keep GET `/api/v1/tasks?project_id={uuid}` and hidden `/tasks` alias, returning
  `{items,total}`. Add optional `q` (trimmed, maximum 200 characters, reject NUL).
  Omitted, empty or whitespace-only q means no search. Case-insensitive literal
  substring match on title OR description; null description matches nothing.
  Percent, underscore and backslash are literal, not wildcard operators. Normalize
  search consistently in service/cache and SQL/in-memory matching; no stemming,
  fuzzy matching, tokenization, ranking, accent folding or full-text framework.
  Unicode case handling follows PostgreSQL lower/collation behavior; tests cover
  ordinary mixed case and Vietnamese, not unsupported Unicode equivalences.
- Combine search AND existing status/priority/assignee filters AND project scope.
  Reuse current newest `(created_at,id)` descending ordering, total before slicing,
  one-based page, default limit 20, cap 200. Out-of-range page returns empty items
  with the matching total. Continue rejecting public offset with 422.
- Preserve enum/UUID/page validation 422, authentication 401, hidden resource 404,
  archived-project read behavior and the existing RBAC policy. A successful list
  has the same fields regardless of the authorized workspace member reading it.
  Authenticate and authorize from the database BEFORE any cache operation on every
  request, including cache hits. Never cache principals, grants, denials or errors.
  A revoked, inactive, outsider or deleted-resource request cannot read cached data.
- No relational schema change is required. Preserve labels/comments and all Day 5
  locking and transaction boundaries. API handles HTTP only; service orchestrates
  use cases/auth/cache; pure policy has no I/O; repositories handle SQL/persistence
  only; UoW owns persistence commit/rollback.

## Redis contract and concurrency

Use the smallest asynchronous Redis client dependency and a task-list-specific
cache port plus Redis adapter (needed for service isolation and deterministic
failure/race unit tests). No generic cache/repository framework. A missing optional
`TASKHUB_REDIS_URL` disables caching; document how to enable Redis. Configured Redis
uses bounded connection/socket timeouts and closes its client on app shutdown.

Cache immutable serialized snapshots of task list items and total, not ORM objects
or mutable shared task instances. Validate cached payloads; malformed data is a miss.
Use a versioned namespace, project UUID, project generation and a stable digest of
normalized q/status/priority/assignee/page/limit. Internal offset+limit may encode
the equivalent unique page. No user ID is needed because project list visibility
and payload are identical for all authorized readers; authorization is never cached.
Use data TTL 60 seconds, without extending TTL on cache hit.

Use random project-generation tokens and atomic Redis operations/Lua to prevent
an old in-flight read from publishing into the active generation after invalidation:

1. After authorization, atomically obtain/create a random generation (SET NX).
2. Lookup this query within that generation; on miss query the database.
3. Publish only if the active generation still equals the captured token, using
   an atomic compare-and-set. Missing/recreated/expired generations must not match
   old tokens (avoid numeric reset/ABA). Generation TTL must exceed data TTL.
4. After a successful task create/update/delete commit, rotate the project token
   before returning success. No invalidation before commit or after rollback.
   Refactor early returns inside transaction scopes as needed. Every filter/page
   becomes unreachable together; old entries expire. Concurrent mutations may
   rotate more than once safely. A read already concurrent with a mutation may
   return its observed older result but cannot poison subsequent cache fills.

Labels/comments are absent from the task-list payload, filters and ordering;
their changes do not require invalidation. Workspace/project deletion is protected
by fresh parent existence/authorization before lookup: residual entries cannot be
served and expire within TTL. No project-delete endpoint exists to extend here.
Future changes exposing label/comment fields or project moves must add invalidation.
Direct SQL writes outside these services are outside the invalidation contract.

Redis connection/timeouts/get/set/rotation errors must not fail database-backed
reads or change the result of an already committed mutation. Log a concise warning
without URLs/secrets/payloads and fall back to database or skip cache fill. No
rollback attempt after committed data merely because invalidation failed.
Explicit availability tradeoff: if post-commit rotation fails while another client
can still read old Redis entries, authorized readers may observe cached snapshots
until their original 60-second TTL expires, measured from snapshot fill, not from
mutation commit. An already in-flight database read may fill after commit when
rotation itself fails. This is bounded snapshot lifetime, never an authorization
bypass. Do not claim strict consistency across Redis outages. Cache
recovery or generation eviction cannot resurrect an old token through token reuse.

Adapter implementation references: Redis documents atomic script execution in
[Lua scripting](https://redis.io/docs/latest/develop/programmability/eval-intro/)
and shared asynchronous clients with explicit shutdown in
[redis-py async operations](https://redis.io/docs/latest/develop/clients/redis-py/async/).

## Acceptance and validation

- Search works on title/description, null/empty strings, casing, Unicode and literal
  SQL wildcard characters; AND filters, counts, page boundaries and project isolation
  remain correct in real PostgreSQL and in-memory persistence.
- API canonical/alias/OpenAPI expose q and preserve all validation contracts.
- Tests prove authorization precedes cache lookup, repeated queries hit, keys isolate
  all normalized query dimensions/projects, snapshots round-trip without mutable
  aliasing, malformed entries miss, TTL expires and absent Redis disables cache.
- Tests prove create/update/delete invalidate all list variants only after commit,
  rollback/commit failure do not invalidate, concurrent read/rotation cannot fill
  active cache with pre-mutation data, and old tokens cannot return after eviction.
- Test Redis read/write/rotation failures and database fallback; successful commits
  remain successful. Test revoked access and workspace deletion against warm cache.
- Run unittest (never pytest), Ruff and git diff checks; independently review changes.
  Run full PostgreSQL tests only against verified disposable `taskhub-day5-db`,
  database `taskhub_test`, and Redis integration against a dedicated disposable
  Task6 Redis container/namespace. Never use the app database or flush shared Redis.
- README/.env.example document q, cache enablement, TTL, invalidation, race guarantee,
  outage tradeoff, test setup and existing routes. No commit, push or Task6 PR until
  explicitly requested. One implementation writer on this shared checkout.

## Work packages

1. Worker: implement q end-to-end with focused unittest coverage; then implement the
   task-list cache port/adapter, wiring, post-commit rotation and race/failure tests.
   Preserve existing filter/pagination rather than redesigning them. Update docs.
2. Coordinator: independently inspect all changes, inspect Redis atomicity and
   authorization/commit ordering, run disposable Postgres/Redis integration and full
   validation. Send concrete fixes back to the sole worker; review until complete.

## Completion checkpoint — 2026-11-16

Implemented and independently reviewed through Herdr worker `day6_impl` (w2:pE),
with coordinator w2:pD. The worker remains available; Day 5 panes were preserved.
The final checkout is on `feat/day6-search-filter-pagination-caching`, HEAD e308605;
all Task6 changes are uncommitted. No push or Task6 PR was created.

Final validation: **124 unittest tests passed, no skips**, in 50.507 seconds,
including PostgreSQL migration/concurrency tests, real Redis Lua/TTL/serialization
tests, HTTP lifespan/DI cache hit and PATCH invalidation, and unavailable-client
fallback. Ruff `check app tests` and `git diff --check` passed. The coordinator
corrected async Retry wiring and ensured the unavailable-client test uses its own
bound ephemeral socket rather than any existing Redis service.

The full run used `TASKHUB_TEST_DATABASE_URL` targeting the verified disposable
`taskhub-day5-db` PostgreSQL 16 container, database `taskhub_test`, and
`TASKHUB_TEST_REDIS_URL=redis://127.0.0.1:6380/0` targeting dedicated
`taskhub-day6-redis` (Redis 7.4.12). Integration tests delete only their own Redis
namespace/project keys; migration teardown returns the test DB to base. Both test
containers remain running. No application database was used. The full validation
log is `%TEMP%/taskhub-day6-final-full-tests.log`.

Enable application caching explicitly through `TASKHUB_REDIS_URL`; it is disabled
when unset/blank. The outage tradeoff above remains intentional: snapshot TTL is
measured from cache fill, without a durable distributed invalidation guarantee.
