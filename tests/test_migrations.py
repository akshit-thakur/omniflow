import ast
import importlib.util
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
import types
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
API_PATH = str(ROOT / "api")


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_function(path: Path, function_name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == function_name
    )
    namespace = {"re": re}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[function_name]


class SchemaBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.initial_split = staticmethod(_load_function(
            ROOT / "alembic" / "versions" / "001_initial_schema.py",
            "_split_sql_statements",
        ))
        cls.reconcile_split = staticmethod(_load_function(
            ROOT / "alembic" / "versions" / "004_reconcile_bigint_runtime.py",
            "_split_sql_statements",
        ))
        sqlalchemy = types.ModuleType("sqlalchemy")
        sqlalchemy.create_engine = MagicMock()
        sqlalchemy.text = lambda value: value
        with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy}):
            cls.runner = _load_module(
                "omniflow_migration_runner",
                ROOT / "scripts" / "run_migrations.py",
            )

    def _target(self, *, name="omniflow", user="configured"):
        return self.runner.DatabaseTarget(
            url=f"postgresql+psycopg://{user}:secret@database:5432/{name}",
            user=user,
            password="secret",
            host="database",
            port=5432,
            name=name,
        )

    def test_canonical_schema_has_only_the_runtime_table_set(self):
        sql = (ROOT / "database" / "init.sql").read_text(encoding="utf-8")
        tables = set(
            re.findall(
                r"^CREATE\s+TABLE\s+IF\s+NOT\s+EXISTS\s+([a-z_]+)",
                sql,
                flags=re.IGNORECASE | re.MULTILINE,
            )
        )
        self.assertEqual(
            {
                "tasks",
                "medications",
                "medication_plans",
                "medication_plan_times",
                "medication_logs",
                "exercise_catalog",
                "training_sets",
                "training_set_exercises",
                "workout_sessions",
                "workout_session_exercises",
                "ingredients",
                "recipes",
                "recipe_ingredients",
                "inventory",
                "meal_entries",
                "media_items",
                "ai_entity_embeddings",
                "ai_action_requests",
                "ai_action_proposals",
                "ai_mutation_audit",
            },
            tables,
        )
        self.assertNotIn("CREATE TABLE IF NOT EXISTS medicines", sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS media_master", sql)
        self.assertNotIn("CREATE TABLE IF NOT EXISTS task_logs", sql)
        self.assertIn("DROP TABLE IF EXISTS finance_transactions CASCADE", sql)

    def test_offline_sync_revision_drops_leftover_sync_triggers(self):
        source = (
            ROOT / "alembic" / "versions" / "006_remove_offline_sync.py"
        ).read_text(encoding="utf-8")
        self.assertIn("set_sync_columns", source)
        self.assertIn("record_sync_tombstone", source)
        self.assertIn("pg_trigger", source)
        self.assertIn("DROP TABLE IF EXISTS finance_transactions CASCADE", source)

    def test_both_migrations_parse_the_same_balanced_sql(self):
        sql = (ROOT / "database" / "init.sql").read_text(encoding="utf-8")
        initial_statements = self.initial_split(sql)
        reconcile_statements = self.reconcile_split(sql)
        self.assertEqual(initial_statements, reconcile_statements)
        self.assertGreater(len(initial_statements), 50)
        self.assertTrue(all(statement.strip() for statement in initial_statements))

    def test_constraint_hardening_revision_covers_model_invariants(self):
        path = ROOT / "alembic" / "versions" / "007_harden_domain_constraints.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assignments = {
            target.id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name)
            and target.id in {"revision", "down_revision", "CHECKS", "ID_TABLES"}
        }

        self.assertEqual("007_harden_domain_constraints", assignments["revision"])
        self.assertEqual("006_remove_offline_sync", assignments["down_revision"])
        checks = {
            (table, name): predicate
            for table, name, predicate in assignments["CHECKS"]
        }
        self.assertEqual(
            "release_year IS NULL OR release_year BETWEEN 1000 AND 9999",
            checks[("media_items", "chk_media_items_release_year")],
        )
        self.assertEqual(
            "progress_total IS NULL OR progress_current <= progress_total",
            checks[("media_items", "chk_media_items_progress_order")],
        )
        self.assertEqual(
            "jsonb_typeof(details) = 'array'",
            checks[
                (
                    "workout_session_exercises",
                    "chk_workout_session_exercises_details_array",
                )
            ],
        )
        self.assertIn("ai_mutation_audit", assignments["ID_TABLES"])

    def test_api_requires_the_current_revision(self):
        source = (ROOT / "api" / "app" / "db.py").read_text(encoding="utf-8")
        self.assertIn(
            'EXPECTED_ALEMBIC_REVISION = "010_finite_numeric_constraints"',
            source,
        )

    def test_ai_approval_revision_is_fresh_bootstrap_safe(self):
        source = (
            ROOT / "alembic" / "versions" / "008_add_ai_action_approval.py"
        ).read_text(encoding="utf-8")
        self.assertIn('revision = "008_add_ai_action_approval"', source)
        self.assertIn('down_revision = "007_harden_domain_constraints"', source)
        self.assertIn("CREATE TABLE IF NOT EXISTS ai_action_requests", source)
        self.assertIn("CREATE TABLE IF NOT EXISTS ai_action_proposals", source)
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_ai_action_requests_pending", source)

    def test_sql_splitter_ignores_semicolons_inside_sql_syntax(self):
        sql = """
        BEGIN;
        -- a comment containing ; is not a statement boundary
        SELECT ';' AS value, "semi;colon" AS "quoted;identifier";
        /* outer ; /* nested ; */ comment ; */ SELECT E'escaped\\';value';
        DO $body$ BEGIN RAISE NOTICE 'inside;body'; END; $body$;
        COMMIT;
        """
        expected = [
            "-- a comment containing ; is not a statement boundary\n"
            "        SELECT ';' AS value, \"semi;colon\" AS \"quoted;identifier\"",
            "/* outer ; /* nested ; */ comment ; */ SELECT E'escaped\\';value'",
            "DO $body$ BEGIN RAISE NOTICE 'inside;body'; END; $body$",
        ]
        self.assertEqual(expected, self.initial_split(sql))
        self.assertEqual(expected, self.reconcile_split(sql))

    def test_sql_splitter_rejects_unterminated_input(self):
        for sql in ("SELECT 'unterminated", "SELECT $$unterminated", "/* open"):
            with self.subTest(sql=sql):
                with self.assertRaises(ValueError):
                    self.initial_split(sql)
                with self.assertRaises(ValueError):
                    self.reconcile_split(sql)

    def test_password_file_is_used_and_uri_encoded(self):
        with TemporaryDirectory() as directory:
            password_file = Path(directory) / "database-password"
            password_file.write_text("s:e/c ret\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "DATABASE_PASSWORD_FILE": str(password_file),
                    "DATABASE_USER": "omniflow",
                    "DATABASE_HOST": "database",
                    "DATABASE_NAME": "omniflow",
                },
                clear=True,
            ):
                url = self.runner.build_database_url()

        self.assertEqual(
            "postgresql+psycopg://omniflow:s%3Ae%2Fc%20ret@database:5432/omniflow",
            url,
        )

    def test_password_file_rejects_ambiguous_direct_password(self):
        with TemporaryDirectory() as directory:
            password_file = Path(directory) / "database-password"
            password_file.write_text("secret\n", encoding="utf-8")
            with patch.dict(
                os.environ,
                {
                    "DATABASE_PASSWORD_FILE": str(password_file),
                    "DATABASE_PASSWORD": "different",
                },
                clear=True,
            ):
                with self.assertRaisesRegex(RuntimeError, "not both"):
                    self.runner.build_database_url()

    def test_wait_retries_transient_connection_failure(self):
        engine = MagicMock()
        connection_context = MagicMock()
        engine.connect.side_effect = [RuntimeError("warming up"), connection_context]
        with (
            patch.dict(
                os.environ,
                {
                    "DATABASE_CONNECT_ATTEMPTS": "2",
                    "DATABASE_CONNECT_RETRY_SECONDS": "0",
                },
                clear=True,
            ),
            patch.object(self.runner.time, "sleep") as sleep,
        ):
            self.assertIsNone(self.runner.wait_for_database(engine))

        sleep.assert_called_once_with(0.0)
        self.assertEqual(2, engine.connect.call_count)

    def test_authentication_failure_without_sqlstate_does_not_retry(self):
        engine = MagicMock()
        engine.connect.side_effect = RuntimeError(
            'FATAL: password authentication failed for user "omniflow"'
        )
        with (
            patch.dict(
                os.environ,
                {
                    "DATABASE_CONNECT_ATTEMPTS": "30",
                    "DATABASE_CONNECT_RETRY_SECONDS": "1",
                },
                clear=True,
            ),
            patch.object(self.runner.time, "sleep") as sleep,
        ):
            error = self.runner.wait_for_database(engine)

        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(1, engine.connect.call_count)
        sleep.assert_not_called()

    def test_main_reconciles_failed_target_then_runs_alembic(self):
        first_engine = MagicMock()
        second_engine = MagicMock()
        connection_error = RuntimeError("login failed")
        connection_results = iter((connection_error, None))
        database_url = (
            "postgresql+psycopg://configured:secret@database:5432/omniflow"
        )
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(
                self.runner,
                "build_database_url",
                return_value=database_url,
            ),
            patch.object(
                self.runner,
                "create_engine",
                side_effect=[first_engine, second_engine],
            ),
            patch.object(
                self.runner,
                "wait_for_database",
                side_effect=lambda _engine: next(connection_results),
            ),
            patch.object(self.runner, "reconcile_database") as reconcile,
            patch.object(self.runner.subprocess, "check_call") as check_call,
        ):
            self.assertEqual(0, self.runner.main())

        reconcile.assert_called_once_with(database_url, connection_error)
        first_engine.dispose.assert_called_once_with()
        second_engine.dispose.assert_called_once_with()
        self.assertEqual(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            check_call.call_args.args[0],
        )
        self.assertEqual(database_url, check_call.call_args.kwargs["env"]["DATABASE_URL"])

    def test_main_delegates_all_schema_state_to_alembic(self):
        engine = MagicMock()
        database_url = (
            "postgresql+psycopg://configured:secret@database:5432/omniflow"
        )
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(
                self.runner,
                "build_database_url",
                return_value=database_url,
            ),
            patch.object(self.runner, "create_engine", return_value=engine),
            patch.object(self.runner, "wait_for_database", return_value=None),
            patch.object(self.runner.subprocess, "check_call") as check_call,
        ):
            self.assertEqual(0, self.runner.main())

        check_call.assert_called_once_with(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            env=unittest.mock.ANY,
        )
        self.assertEqual(database_url, check_call.call_args.kwargs["env"]["DATABASE_URL"])
        engine.dispose.assert_called_once_with()

    def test_configured_migration_lock_wraps_the_whole_operation(self):
        with TemporaryDirectory() as directory:
            lock_path = str(Path(directory) / "migration.lock")
            with (
                patch.dict(
                    os.environ,
                    {"DATABASE_MIGRATION_LOCK_FILE": lock_path},
                    clear=True,
                ),
                patch.object(self.runner, "_run_migrations", return_value=17) as run,
            ):
                self.assertEqual(17, self.runner.main())

            run.assert_called_once_with()
            self.assertTrue(Path(lock_path).is_file())

    def test_failed_target_without_socket_has_actionable_diagnostic(self):
        target = self.runner.DatabaseTarget(
            url="postgresql+psycopg://configured:secret@database:5432/omniflow",
            user="configured",
            password="secret",
            host="database",
            port=5432,
            name="omniflow",
        )
        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.runner, "_database_target", return_value=target),
        ):
            with self.assertRaisesRegex(RuntimeError, "no trusted local"):
                self.runner.reconcile_database(target.url, RuntimeError("failed"))

    def test_reconciliation_creates_missing_login_and_empty_database(self):
        target = self._target(name="newdb", user="custom_role")
        admin_engine = MagicMock()
        inspect_connection = MagicMock()
        inspect_context = MagicMock()
        inspect_context.__enter__.return_value = inspect_connection
        mutate_connection = MagicMock()
        mutate_context = MagicMock()
        mutate_context.__enter__.return_value = mutate_connection
        admin_engine.connect.side_effect = [inspect_context, mutate_context]

        missing_role = MagicMock()
        missing_role.first.return_value = None
        missing_database = MagicMock()
        missing_database.scalar.return_value = None
        inspect_connection.execute.side_effect = [missing_role, missing_database]

        with (
            patch.dict(os.environ, {}, clear=True),
            patch.object(self.runner, "_database_target", return_value=target),
            patch.object(self.runner, "_trusted_socket", return_value="/socket"),
            patch.object(
                self.runner,
                "_find_trusted_admin",
                return_value=("omniflow", "postgres"),
            ),
            patch.object(self.runner, "create_engine", return_value=admin_engine),
            patch.object(self.runner, "_format_and_execute") as execute,
        ):
            self.runner.reconcile_database(target.url, RuntimeError("failed"))

        self.assertEqual(2, execute.call_count)
        self.assertIn("CREATE ROLE", execute.call_args_list[0].args[1])
        self.assertIn("CREATE DATABASE", execute.call_args_list[1].args[1])
        admin_engine.dispose.assert_called_once_with()

    def test_existing_role_database_creation_precedes_password_rotation(self):
        target = self._target(name="newdb")
        admin_engine = MagicMock()
        inspect_connection = MagicMock()
        inspect_context = MagicMock()
        inspect_context.__enter__.return_value = inspect_connection
        mutate_connection = MagicMock()
        mutate_context = MagicMock()
        mutate_context.__enter__.return_value = mutate_connection
        admin_engine.connect.side_effect = [inspect_context, mutate_context]

        existing_role = MagicMock()
        existing_role.first.return_value = (True, True)
        missing_database = MagicMock()
        missing_database.scalar.return_value = None
        inspect_connection.execute.side_effect = [existing_role, missing_database]

        with (
            patch.object(self.runner, "_database_target", return_value=target),
            patch.object(self.runner, "_trusted_socket", return_value="/socket"),
            patch.object(
                self.runner,
                "_find_trusted_admin",
                return_value=("configured", "postgres"),
            ),
            patch.object(self.runner, "create_engine", return_value=admin_engine),
            patch.object(self.runner, "_format_and_execute") as execute,
        ):
            self.runner.reconcile_database(
                target.url,
                RuntimeError(
                    'FATAL: password authentication failed for user "configured"'
                ),
            )

        self.assertEqual(2, execute.call_count)
        self.assertIn("CREATE DATABASE", execute.call_args_list[0].args[1])
        self.assertIn("ALTER ROLE", execute.call_args_list[1].args[1])
        admin_engine.dispose.assert_called_once_with()


class ConstraintDiagnosticTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sqlalchemy = types.ModuleType("sqlalchemy")
        sqlalchemy.create_engine = MagicMock()
        sqlalchemy.text = lambda value: value
        with patch.dict(sys.modules, {"sqlalchemy": sqlalchemy}):
            runner = _load_module(
                "omniflow_migration_runner_for_constraints",
                ROOT / "scripts" / "run_migrations.py",
            )
            with patch.dict(sys.modules, {"run_migrations": runner}):
                cls.checker = _load_module(
                    "omniflow_check_constraints",
                    ROOT / "scripts" / "check_constraints.py",
                )

    def _engine_returning(self, *query_results):
        engine = MagicMock()
        conn = MagicMock()
        engine.connect.return_value.__enter__.return_value = conn
        conn.execute.side_effect = query_results
        return engine, conn

    def test_finds_only_convalidated_false_constraints(self):
        result = MagicMock()
        result.all.return_value = [
            ("tasks", "chk_tasks_title_length", "CHECK (char_length(btrim(title)) BETWEEN 1 AND 500)"),
        ]
        engine, _conn = self._engine_returning(result)

        found = self.checker.find_invalid_check_constraints(engine)

        self.assertEqual(
            [("tasks", "chk_tasks_title_length", "CHECK (char_length(btrim(title)) BETWEEN 1 AND 500)")],
            found,
        )

    def test_count_violations_strips_check_wrapper_and_counts(self):
        result = MagicMock()
        result.scalar_one.return_value = 3
        engine, conn = self._engine_returning(result)

        violations = self.checker.count_violations(
            engine, "tasks", "char_length(btrim(title)) BETWEEN 1 AND 500"
        )

        self.assertEqual(3, violations)
        executed_sql = str(conn.execute.call_args[0][0])
        self.assertIn('FROM "tasks"', executed_sql)
        self.assertIn("char_length(btrim(title)) BETWEEN 1 AND 500", executed_sql)

    def test_main_reports_clean_when_nothing_invalid(self):
        list_result = MagicMock()
        list_result.all.return_value = []
        engine, _conn = self._engine_returning(list_result)

        with patch.object(self.checker, "create_engine", return_value=engine):
            self.assertEqual(0, self.checker.main())
        engine.dispose.assert_called_once_with()

    def test_main_fails_when_a_constraint_still_has_violating_rows(self):
        list_result = MagicMock()
        list_result.all.return_value = [
            ("tasks", "chk_tasks_title_length", "CHECK (char_length(btrim(title)) BETWEEN 1 AND 500)"),
        ]
        count_result = MagicMock()
        count_result.scalar_one.return_value = 2
        engine, _conn = self._engine_returning(list_result, count_result)

        with patch.object(self.checker, "create_engine", return_value=engine):
            self.assertEqual(1, self.checker.main())

    def test_main_succeeds_when_invalid_constraint_has_no_violations_left(self):
        list_result = MagicMock()
        list_result.all.return_value = [
            ("tasks", "chk_tasks_title_length", "CHECK (char_length(btrim(title)) BETWEEN 1 AND 500)"),
        ]
        count_result = MagicMock()
        count_result.scalar_one.return_value = 0
        engine, _conn = self._engine_returning(list_result, count_result)

        with patch.object(self.checker, "create_engine", return_value=engine):
            self.assertEqual(0, self.checker.main())


@unittest.skipUnless(
    os.getenv("RUN_DB_TESTS") == "1",
    "Set RUN_DB_TESTS=1 with a running PostgreSQL stack to run integration tests",
)
class SchemaConstraintIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        while API_PATH in sys.path:
            sys.path.remove(API_PATH)
        sys.path.insert(0, API_PATH)
        from app.db import open_pool

        await open_pool()

    async def asyncTearDown(self):
        from app.db import close_pool

        await close_pool()
        while API_PATH in sys.path:
            sys.path.remove(API_PATH)
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]

    async def test_revision_constraints_are_installed_validated_and_enforced(self):
        import asyncpg
        from datetime import date

        from app.db import connection

        path = ROOT / "alembic" / "versions" / "007_harden_domain_constraints.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        assignments = {
            target.id: ast.literal_eval(node.value)
            for node in tree.body
            if isinstance(node, ast.Assign)
            for target in node.targets
            if isinstance(target, ast.Name) and target.id in {"CHECKS", "ID_TABLES"}
        }
        expected_names = {
            name for _table, name, _predicate in assignments["CHECKS"]
        } | {
            f"chk_{table}_id_positive" for table in assignments["ID_TABLES"]
        }

        async with connection() as conn:
            installed = await conn.fetch(
                """SELECT conname,convalidated FROM pg_constraint
                   WHERE conname=ANY($1::text[])""",
                sorted(expected_names),
            )
        self.assertEqual(expected_names, {row["conname"] for row in installed})
        self.assertTrue(all(row["convalidated"] for row in installed))

        async with connection() as conn:
            media_id = await conn.fetchval(
                """INSERT INTO media_items(
                     title,media_type,release_year,progress_current,progress_total
                   ) VALUES($1,$2,$3,$4,$5) RETURNING id""",
                "Constraint edge",
                "book",
                1000,
                1,
                1,
            )
        try:
            cases = (
                (
                    "INSERT INTO tasks(id,title) VALUES($1,$2)",
                    (0, "Invalid id"),
                    "chk_tasks_id_positive",
                ),
                (
                    """INSERT INTO media_items(title,media_type,release_year)
                       VALUES($1,$2,$3)""",
                    ("Invalid year", "book", 999),
                    "chk_media_items_release_year",
                ),
                (
                    """INSERT INTO media_items(
                         title,media_type,progress_current,progress_total
                       ) VALUES($1,$2,$3,$4)""",
                    ("Invalid progress", "book", 2, 1),
                    "chk_media_items_progress_order",
                ),
                (
                    """INSERT INTO workout_sessions(set_name,session_date)
                       VALUES($1,$2)""",
                    ("   ", date(2026, 8, 25)),
                    "chk_workout_sessions_set_name",
                ),
            )
            async with connection() as conn:
                for query, arguments, constraint_name in cases:
                    with self.subTest(constraint=constraint_name):
                        with self.assertRaises(asyncpg.CheckViolationError) as raised:
                            async with conn.transaction():
                                await conn.execute(query, *arguments)
                        self.assertEqual(
                            constraint_name,
                            raised.exception.constraint_name,
                        )
        finally:
            async with connection() as conn:
                await conn.execute("DELETE FROM media_items WHERE id=$1", media_id)

    async def test_revision_downgrade_upgrade_cycle_preserves_preexisting_row(self):
        from datetime import date

        from app.db import connection

        executed: list[str] = []
        alembic = types.ModuleType("alembic")
        alembic.op = types.SimpleNamespace(execute=executed.append)
        path = ROOT / "alembic" / "versions" / "007_harden_domain_constraints.py"
        with patch.dict(sys.modules, {"alembic": alembic}):
            revision = _load_module("constraint_cycle_revision", path)

        revision.downgrade()
        downgrade_statements = tuple(executed)
        executed.clear()
        revision.upgrade()
        upgrade_statements = tuple(executed)
        expected_names = {
            name for _table, name, _predicate in revision.CHECKS
        } | {
            f"chk_{table}_id_positive" for table in revision.ID_TABLES
        }

        async with connection() as conn:
            transaction = conn.transaction()
            await transaction.start()
            try:
                for statement in downgrade_statements:
                    await conn.execute(statement)
                workout_id = await conn.fetchval(
                    """INSERT INTO workout_sessions(set_name,session_date)
                       VALUES($1,$2) RETURNING id""",
                    "Pre-007 workout",
                    date(2026, 8, 25),
                )
                for statement in upgrade_statements:
                    await conn.execute(statement)

                stored_name = await conn.fetchval(
                    "SELECT set_name FROM workout_sessions WHERE id=$1",
                    workout_id,
                )
                installed = await conn.fetch(
                    """SELECT conname,convalidated FROM pg_constraint
                       WHERE conname=ANY($1::text[])""",
                    sorted(expected_names),
                )
                self.assertEqual("Pre-007 workout", stored_name)
                self.assertEqual(
                    expected_names,
                    {row["conname"] for row in installed},
                )
                self.assertTrue(all(row["convalidated"] for row in installed))

                for statement in downgrade_statements:
                    await conn.execute(statement)
                remaining = await conn.fetchval(
                    """SELECT count(*) FROM pg_constraint
                       WHERE conname=ANY($1::text[])""",
                    sorted(expected_names),
                )
                self.assertEqual(0, remaining)

                for statement in upgrade_statements:
                    await conn.execute(statement)
                restored = await conn.fetchval(
                    """SELECT count(*) FROM pg_constraint
                       WHERE conname=ANY($1::text[]) AND convalidated""",
                    sorted(expected_names),
                )
                self.assertEqual(len(expected_names), restored)
            finally:
                await transaction.rollback()


if __name__ == "__main__":
    unittest.main()
