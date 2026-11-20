# Day 7 follow-up: search/filter/page/cache review

## Scope and source — 2026-11-18

User requests a renewed check of the files in
`C:/Users/ADMIN/Downloads/taskhub`, completion of searching/filtering/pagination/
caching, and clean separation of responsibilities to reduce repeated review fixes.
All four images were inspected again. They group days 3–7 into Business Logic &
Core Features, without assigning specific features to a separate Day 7. Features
8/9 cover filters, page+limit and Redis task-list invalidation. User-requested
search remains the Day 6 literal substring contract. This review does not claim
all Day 7/core features are complete or add project CRUD/email/notifications.

Source assessment is specific to this scope: feature 8 is the existing Day 5
filter/page contract; feature 9 and user-requested search are the Day 6 work under
renewed review. Source feature 4 (project CRUD), feature 10 (assignment email),
feature 13 (full-stack Docker Compose) and the separate final type-check/review
requirements must not be inferred complete from passing this feature suite.

Baseline is HEAD e308605; current Day 6 work is uncommitted on
`feat/day6-search-filter-pagination-caching`. Preserve these changes. The previous
124-test completion checkpoint belongs to 2026-11-16 and is historical, not a claim
about today's test environment. No commit/push/PR is authorized.

## Initial independent findings — resolved

1. Standards/architecture (judgment): `services/task_list_cache.py` combined an
   application port and query digest with concrete Redis/Lua I/O and serialization
   coupled to the HTTP `TaskRead` model. Keep the small application cache contract
   in services; place the Redis adapter and snapshot codec in a cache/infrastructure
   package, and give the snapshot its own validated representation. Preserve the
   domain's framework independence. Split by responsibility, not arbitrary size;
   do not add a generic framework or pass-through modules.
2. Spec/correctness (P2): `TaskRepository.list` read page rows and COUNT with two
   READ COMMITTED statements. A concurrent delete/filter update can return items
   and total from different snapshots and cache an incoherent response. Read both
   in one PostgreSQL statement, including correct total for empty/out-of-range
   pages. Keep SQL in the repository; preserve AND search/filter predicates and
   deterministic ordering. Capture a regression that fails before this fix.

Also review actual warm-cache revocation/deletion coverage, malformed cache values,
configuration validation and failure logs; fix concrete problems and add targeted
checks. Keep the documented outage TTL tradeoff rather than introducing an outbox.
Cancellation after commit has the same bounded snapshot lifetime caveat; avoid
claiming durable invalidation. Python/PostgreSQL Unicode lower differences are
outside the documented Unicode-equivalence guarantee unless a supported case fails.

## Coordination and verification

- User explicitly requires the existing Herdr worker pane and automatic compaction.
  Resumed existing `day6_impl` session 01a1e2b7-ad78-7e20-b4ab-bdff8a532e96 in
  verified open pane w2:pE, tab w2:t4; no replacement pane was created. Coordinator
  owns this spec/checkpoint and tests; worker is the sole implementation writer.
- Parallel read-only standards/spec reviewers found the two items above; neither
  edited code or ran database tests. Review final repairs independently.
- Docker was stopped on arrival; Docker Desktop start was requested through the
  environment's approval mechanism. Re-verify test containers/databases before any
  integration run. Use only disposable PostgreSQL `taskhub_test` and dedicated
  Task6 Redis; never write application DB or flush shared Redis.
- Use unittest, Ruff and diff checks. Run targeted regressions, then the full suite
  against real PostgreSQL/Redis after repairs. Preserve public flat routes/aliases,
  auth-before-cache, post-commit rotation, Lua CAS and rollback behavior.
- Before compaction, update this file with completed/pending work and exact test
  results. Worker may compact only its own session after persisting its checkpoint;
  coordinator context compaction must preserve the same ongoing task.

## Final checkpoint — complete, 2026-11-18

Searching, filtering, pagination and Redis task-list caching are implemented and
verified within the Day 6 contract. Both initial review findings are repaired;
independent Standards and Spec re-reviews report no remaining material findings
in this scope. No additional feature or dependency was introduced by this review.

The cache application port/query identity stays in `services/task_list_cache.py`;
`cache/redis_task_list_cache.py` owns Redis/Lua I/O and
`cache/task_list_snapshot.py` owns the HTTP-independent validated snapshot format.
The existing v1 JSON shape remains compatible. Tests enforce import direction and
exercise the actual adapter's rejection of validly-shaped wrong-project data,
with a same-project positive control. Repositories retain SQL and locking only;
services retain use-case/auth/cache orchestration and UoW transaction ownership.

Task page and matching total now come from one PostgreSQL statement, including
empty/out-of-range totals. Explicit outer ORDER BY preserves descending
`(created_at,id)` order as well as the subquery ordering used to select the page.
The coordinator proved the real concurrent-delete regression rejects the previous
algorithm: two returned items with total 1 instead of 2, exactly one assertion
failure. Repaired source passed that regression and six focused checks (7 tests,
6.370s). Evidence is in `%TEMP%/taskhub-day7-red-proof.log` and
`%TEMP%/taskhub-day7-focused-green.log`; the old algorithm was patched only in the
test process, without modifying source.

Redis URL validation accepts redis/rediss with optional credentials and a numeric
DB path, and rejects query overrides, fragments, whitespace, missing host and
invalid ports/paths. This prevents URL query options from overriding the bounded
client timeout (30s versus configured 0.5s was reproduced before the guard).
Settings errors hide raw input. Parsing, port and hostname errors are replaced
with a generic message, including NFKC-invalid Unicode hostname errors which
otherwise embed credential-bearing netlocs. Both credential probes pass and the
worker observed the Unicode regression red before fixing it.

The original worker session was successfully compacted via `/compact` in w2:pE
after saving `specs/day7-worker-checkpoint.md`; the coordinator observed
`Context compacted · 24s` with the same session ID. The implementation is frozen
and no commit, push or PR was created. No required implementation work remains.

Final verification on the frozen source: **128 unittest tests passed, no skips,
57.351s**, with real PostgreSQL and Redis, plus Ruff `check app tests` and
`git diff --check`. Full log: `%TEMP%/taskhub-day7-final-full-tests.log`.
The run includes migration/concurrency, literal search/AND filtering/page counts,
HTTP cache wiring, authorization-before-cache, CAS/TTL, rollback and failure
fallback tests. Earlier green runs are historical; this is the final result.

Docker Desktop is running; existing `taskhub-day5-db` and `taskhub-day6-redis`
were inspected and restarted. PostgreSQL was verified to contain only postgres,
taskhub_test and templates; tests targeted `taskhub_test` only. Redis test endpoint
is `redis://127.0.0.1:6380/0`; tests clean only their own namespace/project keys.
Both containers remain running; no application DB was used or shared Redis flushed.

The documented cache outage/cancellation tradeoff remains intentional: cached
snapshots expire 60 seconds after fill, not a durable invalidation guarantee from
mutation commit. Authentication/authorization are never cached. Enable caching
explicitly with `TASKHUB_REDIS_URL`; blank/unset keeps it disabled.
