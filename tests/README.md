# Tests

## Summary

Run all commands from the repository root with Docker Compose v2.
No host Python, Node, PostgreSQL, or `.env` is required. The Test image runs
unit and contract tests; isolated services run PostgreSQL integration and
migration tests; the same image runs live-stack smoke checks. The demo has a
separate image and Compose project.

## Commands

| Check | Command | PostgreSQL / running stack |
| --- | --- | --- |
| Unit and contract tests | `docker compose --profile tools run --build --rm tests` | Neither; integration classes are skipped |
| Database integration | `docker compose -p omniflow-db-tests --profile tools run --build --rm database-tests` | Starts isolated PostgreSQL and migrations |
| Migration integration | `docker compose -p omniflow-db-tests --profile tools run --build --rm migration-tests` | Isolated PostgreSQL; owner permissions for DDL |
| Frontend lint/typecheck/build | `docker compose build frontend` | Neither |
| Live constraints | `docker compose --profile tools run --build --rm database-check` | Main database; read-only diagnostic |
| Live smoke | `docker compose --profile tools run --build --rm smoke-test` | Complete running stack and models |

The Python services share [one Test Dockerfile](../docker/tests/Dockerfile).
It contains application source, fixtures, dependencies, and tests; no source
bind mounts or local virtual environment are needed. Runtime images do not
include the test suite. API and AI remain isolated services with distinct users
and database permissions. Their identical pinned dependencies can share Docker
cache layers; keeping their small runtime Dockerfiles avoids coupling their releases.

Run an individual module using unittest discovery:

```sh
docker compose --profile tools run --rm tests python -m unittest discover -s tests -p test_credentials.py -v
```

Database tests write and delete records. Never run them against your normal
installation. Inspect and remove only the disposable project when done:

```sh
docker compose -p omniflow-db-tests ps --all
docker compose -p omniflow-db-tests down --volumes
```

## Detailed test coverage

| Module or group         | Coverage                                                                                                                        |                     Requires PostgreSQL | Requires running stack |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------: | ---------------------: |
| `test_ai_actions.py`    | AI write-action allowlists, schemas, argument resolution, handlers, proposal approval/rejection, transaction and audit behavior |                         Some classes do |                     No |
| `test_ai_classifier.py` | Prompt construction, retrieval scope, structured output, chat streaming, health, indexing, and AI-service boundaries            |        `RetrievalIntegrationTests` does |                     No |
| `test_auth.py`          | Operator-session and mutation-boundary checks                                                                                   |                                      No |                     No |
| `test_backups.py`       | Snapshot validation, streaming limits, export/restore transaction behavior                                                      |           `BackupIntegrationTests` does |                     No |
| `test_contracts.py`     | API/frontend contracts, schema boundaries, route exposure, proxy behavior, and readiness checks                                 |                                      No |                     No |
| `test_migrations.py`    | Migration parsing, schema reconciliation, constraints, credentials, retry behavior, and diagnostics                             | `SchemaConstraintIntegrationTests` does |                     No |
| `test_public_routes.py` | Domain route rules for kitchen, gym, media, tasks, and medication                                                               |   `PublicMutationIntegrationTests` does |                     No |
| `test_settings.py`      | File-backed secrets and API/AI configuration validation                                                                         |                                      No |                     No |
| `test_showcase_seed.py` | Empty/partial/complete showcase fixture handling and idempotency                                                                |                                      No |                     No |
| `test_smoke.py`         | Smoke-client configuration, read-only probes, internal-route blocking, and write cleanup using fakes                            |                                      No |                     No |
| `test_credentials.py` | First-run credential persistence, hashing, legacy compatibility, explicit reset, invalid input | No | No |
| `test_activity.py` | Transactional rollback, source attribution, pooled-connection isolation, AI deduplication | Yes | No |

All modules run under the `tests` service; PostgreSQL integration
classes are gated by `RUN_DB_TESTS=1`. Five run under `database-tests`;
`SchemaConstraintIntegrationTests` runs under `migration-tests`.
Mocked tests establish contracts; they do not prove database or model behavior.

### AI behavior

`test_ai_actions.py` checks the allowlisted write-action registry, strict
argument schemas, exact and ambiguity-safe entity resolution, ordered batches,
transaction rollback, audit insertion, approval and rejection behavior, and
the integration path that executes against PostgreSQL.

`test_ai_classifier.py` checks prompt construction, untrusted stored content,
retrieval filters, structured classifier output, streamed chat events, model
and index health, reindex cleanup, and the PostgreSQL retrieval lifecycle.

### API boundaries and domain rules

`test_auth.py` covers first-run setup, one-time setup enforcement, durable
credential changes, session invalidation after reset, normal sign-in, CSRF and
origin checks, and password-free demo behavior.

`test_contracts.py` covers frontend route/API parity, Pydantic boundary rules,
bounded collections, positive identifiers, proxy blocking, AI health proxying,
and migration readiness.

`test_public_routes.py` covers domain-specific kitchen, gym, media, task, and
medication behavior. Its mutation integration class confirms rollback against
PostgreSQL.

### Data safety and migrations

`test_backups.py` checks JSON scalar encoding, streaming size limits, malformed
and orphaned snapshot rejection, repeatable-read export, sequence repair,
pending-proposal invalidation, and transactional restore rollback.

`test_migrations.py` checks canonical schema parsing, balanced SQL splitting,
role/database reconciliation, retry behavior, diagnostics, current revision
requirements, and live constraint enforcement. Migration integration runs with
the database owner because it exercises downgrade/upgrade DDL.

`test_activity.py` checks that activity rows commit and roll back with domain
changes, source attribution is isolated between pooled connections, and AI
changes use the existing AI audit trail without duplicate activity rows.

`test_credentials.py` checks first-run hashing, legacy stored-password support,
one-time setup, explicit reset, fingerprint changes, and invalid input.

### Configuration and supporting tools

`test_settings.py` checks file-backed secrets and API/AI configuration bounds.
`test_showcase_seed.py` checks safe empty-database seeding, partial-fixture
rejection, and idempotent complete-fixture verification.
`test_smoke.py` checks the smoke client, environment-variable URL/port
resolution, health and JSON contracts, private-route blocking, read-only
behavior, and write-cleanup behavior using fakes.

## Running-stack smoke

Finish browser setup and wait for AI/model health first. For a normal installation,
prompt for the operator password (Bash/Zsh); the demo needs no password:

```sh
read -rs SMOKE_OPERATOR_PASSWORD
export SMOKE_OPERATOR_PASSWORD
docker compose --profile tools run --build --rm smoke-test
docker compose --profile tools run --rm smoke-test python -m docker.tests.smoke --write
unset SMOKE_OPERATOR_PASSWORD
```

The default checks read domain data, health, and private-route blocking. Login
creates a session; the domain checks are read-only. `--write` creates a temporary
task, updates it, and attempts cleanup even after failure. The service reaches
Nginx over the Compose network, so custom published host ports need no override.

The showcase equivalent is:

```sh
docker compose -f compose.showcase.yaml --profile tools run --build --rm smoke-test
```

See [verification evidence](VERIFICATION.md) for actual results and limitations.
Host execution is an optional contributor convenience; Docker commands above
are the supported verification path.
