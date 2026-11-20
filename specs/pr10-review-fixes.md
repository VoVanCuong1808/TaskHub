# PR 10 review fixes — 2026-11-19

Baseline: clean local HEAD and PR head `4959fe021defcdaf02d697a358bb5df663148793`,
branch `feat/day6-search-filter-pagination-caching`. PR is open against main.
Read the submitted review and all three inline comments through GitHub API.

## Requested changes

1. [RedisDsn](https://github.com/VoVanCuong1808/TaskHub/pull/10#discussion_r4609426358):
   use `redis_url: RedisDsn | None`, keep only the before-validator turning blank
   strings into None, and delete the custom Redis URL validator. Keep unrelated
   frontend-origin validation intact. Convert DSN to string at Redis integration.
   Adopt Pydantic's native DSN normalization/defaults instead of reproducing old
   custom rules in new validators. Adjust tests and README to the native contract.
2. [Exception diagnostics](https://github.com/VoVanCuong1808/TaskHub/pull/10#discussion_r4609426363):
   add `exc_info=True` on cache read, fill and post-commit invalidation warnings.
   Verify useful exception type/message/traceback is logged on each failure path,
   while reads still fall back and committed writes still succeed. Keep sensitive
   settings and snapshot input hidden in validation error text; do not log tokens,
   Redis URLs or task payloads deliberately.
3. [Named limits](https://github.com/VoVanCuong1808/TaskHub/pull/10#discussion_r4609426369):
   centralize task search maximum length and Redis runtime timeout/pool/retry/TTL
   limits in `app/core/constants.py`, replacing production literals at call sites.
   Keep the current values and behavior (search 200, timeout 0.5s, pool 50,
   no retries, cache data 60s, generation 120s). Test fixture values need not all
   become production constants.

## Compatibility and verification

The coordinator probed the installed Pydantic/Redis clients: RedisDsn accepts query
options and defaults an omitted host to localhost. Therefore remove tests claiming
the old manual-validator rules are still enforced. Preserve application-owned
timeouts, retry and connection limits when constructing the actual Redis client:
native redis-py `parse_url(str(dsn))`, then override owned options, then construct
`ConnectionPool` and `Redis.from_pool` is one minimal supported approach. Pool
ownership was verified: client close closes its pool. No new URL parsing framework
or generic factory is needed. Add a narrow no-network query-override guard test
plus existing real HTTP/Redis integration to validate the wiring.

Preserve HTTP routes, authorization-before-cache, one-statement count/page,
post-commit rotation, rollback semantics and generation CAS. Do not widen scope.
Use unittest only, no pytest or new dependencies. Worker `day6_impl` in existing
pane w2:pE is sole code/test writer. Coordinator owns this plan, independent review
and disposable Postgres/Redis integration. Unrelated pane w2:pF is untouched.

No GitHub review replies/resolution messages are authorized. Earlier user
authorization to push this feature branch remains applicable; after final checks,
coordinator may commit/push these review fixes to the same PR without force-push.
Never stage private `.env` or change application data for the integration run.

## Checkpoint

All three requested changes are implemented and independently reviewed. Original
worker day6_impl/w2:pE was the sole implementation writer and is now idle; its
focused 48-test run passed and it saved `specs/pr10-worker-checkpoint.md`.
Coordinator verified the actual typed RedisDsn HTTP path, native query-option
handling, owned pool shutdown, named limits, all three warning tracebacks and
hidden snapshot validation inputs. No new dependency or generic framework added.

Final coordinator verification on the frozen source: **131 unittest tests passed,
no skips, 48.800 seconds**, including real PostgreSQL/Redis integration and HTTP
cache hit/invalidation. Ruff `check app tests` and `git diff --check` passed.
Log: `%TEMP%/taskhub-pr10-review-tests.log`.

Test target was verified as dedicated taskhub-day5-db (only postgres, taskhub_test
and templates) and taskhub-day6-redis on 6380. Application containers at 5433/6379,
private `.env`, and the unrelated service/pane were left untouched. No GitHub
review reply or thread-resolution message was sent. All three review comments
were rechecked and PR head remained at baseline before coordinator commit/push.
The implementation is complete and frozen, ready for the authorized branch update.
