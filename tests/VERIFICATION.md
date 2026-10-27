# Docker verification record

These checks were run on 17 October 2026 with disposable Compose projects.
The normal application volumes were not used.

## Clean install

The clean project was started with empty database, secret, and model volumes.
The verification confirmed:

- database initialization and Alembic migration to `011_recent_activity`;
- first-run password setup and rejection of a second setup attempt;
- password persistence after container recreation and image rebuild;
- manual task create/update/delete smoke checks;
- backup export, preview, restore, and retained-record behavior;
- manual, restore, and AI activity sources without duplicate AI entries;
- activity pagination;
- frontend, API, database, AI, and model readiness.

The full-stack smoke check passed after model initialization completed.

## Upgrade and recovery

An isolated previous-schema fixture was downgraded to
`010_finite_numeric_constraints`, seeded with a retained task and a legacy
operator password, and then started through the normal Compose migration path.
The migration completed successfully. The retained task and legacy password
remained usable after the upgrade.

The explicit recovery command was also exercised:

```sh
docker compose exec api python -m app.credentials --reset
```

The reset replaced the credential, invalidated existing sessions, and left the
database records intact. Credentials remain in the `api-secrets` volume and are
preserved across rebuilds, upgrades, restarts, and `docker compose down`; they
change only during first-run setup or an explicit reset.

## Test image verification

The dedicated Test image passed:

- 198 host-safe and mocked tests, with the database classes skipped;
- 14 PostgreSQL integration tests;
- 2 owner-permission migration tests;
- frontend ESLint, TypeScript, and production Vite build checks.

The dedicated Demo image was built and the password-free showcase stack was
started separately from the normal installation. The showcase seeder waits for
the API and AI services and uses only the isolated demo data set.
