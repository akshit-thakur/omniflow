# Todo list

- [x] Replace the cumbersome generated-password retrieval flow with a first-run setup screen where the user creates the operator password. Keep normal sign-in afterward and provide an explicit Docker recovery/reset path for a forgotten password.
- [x] Do not require users to create or configure a `.env` file for the default setup; the application should work out of the box with sensible defaults.
- [x] Add a user-facing recent activity view covering approximately the last 7 days, showing who made each change, when it happened, what action was taken, and which record was affected. Reuse the backend audit trail rather than making it backend-only.
- [x] Remove non-Docker installation references from the README and related documentation; describe Docker Compose as the supported installation path while host-based installation is revisited.
- [x] Revisit the demo installation instructions referenced in the README, and verify that the Docker installation path clearly references the appropriate smoke tests.
- [x] Restructure `scripts/` into clear startup/setup, demo tooling, and verification groups while keeping the commands easy to discover.
- [x] Review the Dockerfiles for possible minimization or consolidation, especially duplicated API/AI dependency setup, without weakening service isolation or making the Compose workflow harder to understand.
- [x] Create `tests/README.md` documenting what each test module or test group covers, how it is run, and whether it requires Docker, PostgreSQL, or a running stack. Update it once the testing Docker image is completely built.
- [x] Perform and document a clean-install verification from empty Docker volumes, following only the README instructions and confirming the first-run experience works as described.
- [x] Perform and document an upgrade/recovery verification using an existing Docker volume: apply migrations, preserve data and credentials, test backup/restore, and confirm the documented recovery path is accurate.
- [x] Build and validate the Docker-based testing image and make sure the documented test commands run correctly through it.
- [x] Build and verify the dedicated Docker image/workflow for running the test suite.
- [x] Make Docker Compose the canonical test workflow and document host-based test commands as optional developer shortcuts.
- [x] Replace `scripts/demo/` with a dedicated Demo Docker image and Compose workflow that owns showcase seeding and demo setup.
- [x] Replace `scripts/verification/` with a dedicated Test Docker image and Compose workflow for unit, contract, migration, and PostgreSQL integration tests.
- [x] Move running-stack smoke verification into the Test Docker workflow, preserving read-only and explicit write-check modes.
- [x] Keep `scripts/startup/` as the small set of Docker startup entrypoints for secrets, model downloads, and migrations.
