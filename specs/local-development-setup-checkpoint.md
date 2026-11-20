# Local development setup checkpoint — 2026-11-18

Worker changes are limited to setup documentation and PostgreSQL test settings
isolation. The worker did not read or edit the ignored root `.env`, start Docker,
run migrations, or connect to PostgreSQL/Redis. No commit, push, or PR was made.

## Changes

- README setup now creates `.env` only when absent and persists a random JWT key
  only when the setting is missing or blank. The inline Python does not print the
  key and preserves an existing `.env` and existing key.
- PostgreSQL tests share `isolated_test_settings`, which explicitly disables
  dotenv loading and Redis. A no-network test writes app Redis/JWT/cookie values
  plus a non-explicit setting into a temporary `.env`, then proves the helper
  ignores those values and uses test settings.

## Verification

- `tests.test_postgres.SettingsIsolationTests`: 1 passed; no DB/Redis access.
- Focused Ruff and `git diff --check` passed. Git emitted informational
  LF-to-CRLF notices for existing modified files.
- Coordinator reports local Compose services healthy and local migration
  `92f027da2ac1` applied; app runtime smoke remains coordinator-owned.

## Coordinator runtime completion

User explicitly authorized creating `.env`, enabling Redis and running the local
application. The coordinator created the previously absent, Git-ignored `.env`
with a private randomly generated JWT key (never displayed), PostgreSQL at
`127.0.0.1:5433/taskhub`, Redis at `127.0.0.1:6379/0`, and local HTTP refresh-cookie
configuration. Existing test services remain separate at PostgreSQL 5432 and
Redis 6380. No existing `.env` or application database was overwritten.

`compose.local.yaml` was validated and started with `up -d --wait`. Dedicated
containers `taskhub-local-postgres-1` and `taskhub-local-redis-1` are healthy and
bound to loopback. PostgreSQL uses the newly created durable named volume
`taskhub-local_taskhub_local_postgres`. Migration `92f027da2ac1` is applied.

The app is running in a hidden background process (PID 6004 at verification) on
`http://127.0.0.1:8000`. `/health` and `/docs` both return 200. Process ID and
stdout/stderr are recorded in `%TEMP%/taskhub-local-api.pid`,
`taskhub-local-api.stdout.log` and `taskhub-local-api.stderr.log`.

Real HTTP/Redis verification passed: authenticated project task-list snapshots
were populated with a TTL at most 60 seconds; repeated reads increased actual
Redis keyspace hits; create/update/delete each invalidated the list correctly.
Only a uniquely named temporary smoke task was created and cleaned up. A short
lived local verification token was kept in memory and never displayed/stored; no
login credential or password was changed. The application's task count is zero
after cleanup, and Redis returns PONG.

With the real application `.env` present and the app still running, the full
unittest suite passed **129 tests, no skips, 46.668s**, targeting only the dedicated
`taskhub_test` database and test Redis 6380. The isolation regression proves test
settings ignore application dotenv values. After the suite, the local API still
returns 200, application schema remains at `92f027da2ac1`, application tasks remain
zero, and both local containers are healthy. Ruff and diff checks passed;
`git check-ignore .env` confirms the secret file is ignored.

Full log: `%TEMP%/taskhub-local-env-full-tests.log`. Runtime setup is complete;
the app and dependencies are left running for the user. Implementation is frozen.
No commit, push or PR was created.
