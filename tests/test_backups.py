from contextlib import asynccontextmanager
from datetime import date, datetime, time, timezone
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
API_PATH = str(ROOT / "api")
sys.path.insert(0, API_PATH)

from app.routers import backups  # noqa: E402


class _StreamRequest:
    def __init__(self, chunks):
        self._chunks = chunks
        self.yielded = 0

    async def stream(self):
        for chunk in self._chunks:
            self.yielded += 1
            yield chunk


class _FailingStreamRequest:
    async def stream(self):
        yield b'{"snapshot":'
        raise RuntimeError("client disconnected")


def _snapshot(title="Backup", task_id=1):
    return {
        "snapshot": {
            "format": backups.BACKUP_FORMAT,
            "version": backups.BACKUP_VERSION,
            "module": "tasks",
            "exported_at": "2026-08-25T00:00:00+00:00",
            "tables": {
                "tasks": [
                    {
                        "id": task_id,
                        "title": title,
                        "description": None,
                        "priority": "medium",
                        "completed": False,
                        "due_date": None,
                        "created_at": "2026-08-25T00:00:00+00:00",
                        "updated_at": "2026-08-25T00:00:00+00:00",
                        "completion_date": None,
                    }
                ]
            },
        }
    }


def _manager(conn):
    @asynccontextmanager
    async def manager():
        yield conn

    return manager


def _transaction():
    transaction = MagicMock()
    transaction.__aenter__ = AsyncMock(return_value=transaction)
    transaction.__aexit__ = AsyncMock(return_value=False)
    return transaction


def _connection():
    conn = MagicMock()
    conn.fetch = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetchval = AsyncMock()
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()
    conn.transaction = MagicMock()
    return conn


class BackupBodyTests(unittest.IsolatedAsyncioTestCase):
    def test_json_default_encodes_supported_database_scalars(self):
        self.assertEqual("2026-09-09", backups._json_default(date(2026, 9, 9)))
        self.assertEqual("07:30:00", backups._json_default(time(7, 30)))
        self.assertEqual(
            "2026-09-09T07:30:00+00:00",
            backups._json_default(datetime(2026, 9, 9, 7, 30, tzinfo=timezone.utc)),
        )
        request_id = uuid4()
        self.assertEqual(str(request_id), backups._json_default(request_id))

    async def test_preview_accepts_chunked_body_at_limit(self):
        payload = json.dumps(_snapshot()).encode()
        with patch.object(backups, "MAX_RESTORE_BYTES", len(payload)):
            result = await backups.preview_restore(
                _StreamRequest([payload[:10], payload[10:]])
            )
        self.assertEqual("tasks", result["module"])
        self.assertEqual(1, result["total_rows"])

    async def test_body_over_limit_is_rejected_before_remaining_chunks(self):
        request = _StreamRequest([b"1234", b"5", b"unread"])
        with patch.object(backups, "MAX_RESTORE_BYTES", 4):
            with self.assertRaisesRegex(Exception, "too large"):
                await backups._read_restore_body(request)
        self.assertEqual(2, request.yielded)

        for handler in (backups.preview_restore, backups.restore_backup):
            with self.subTest(handler=handler.__name__):
                request = _StreamRequest([b"1234", b"5", b"unread"])
                with patch.object(backups, "MAX_RESTORE_BYTES", 4):
                    with self.assertRaisesRegex(Exception, "too large"):
                        await handler(request)
                self.assertEqual(2, request.yielded)

    async def test_invalid_json_is_rejected(self):
        with self.assertRaisesRegex(Exception, "UTF-8 JSON"):
            await backups.preview_restore(_StreamRequest([b"not-json"]))
        with self.assertRaisesRegex(Exception, "UTF-8 JSON"):
            await backups.preview_restore(_StreamRequest([b"\xff"]))

    async def test_preview_rejects_invalid_scalar_values_before_restore(self):
        payload = _snapshot()
        payload["snapshot"]["tables"]["tasks"][0]["due_date"] = "not-a-date"
        with self.assertRaisesRegex(Exception, "tasks.due_date"):
            await backups.preview_restore(_StreamRequest([json.dumps(payload).encode()]))

    async def test_preview_accepts_workout_details_arrays(self):
        payload = _snapshot()
        payload["snapshot"]["module"] = "gym"
        payload["snapshot"]["tables"] = {
            table: [] for table in backups.MODULE_TABLES["gym"]
        }
        payload["snapshot"]["tables"]["workout_session_exercises"] = [{
            column: [] if column == "details" else None
            for column in backups.TABLE_COLUMNS["workout_session_exercises"]
        }]
        result = await backups.preview_restore(_StreamRequest([json.dumps(payload).encode()]))
        self.assertEqual("gym", result["module"])

    async def test_preview_rejects_orphaned_child_rows(self):
        payload = _snapshot()
        payload["snapshot"]["module"] = "medications"
        payload["snapshot"]["tables"] = {
            table: [] for table in backups.MODULE_TABLES["medications"]
        }
        payload["snapshot"]["tables"]["medication_plans"] = [{
            column: 99 if column == "medication_id" else (
                1 if column == "id" else (
                    "Plan" if column == "plan_name" else None
                )
            )
            for column in backups.TABLE_COLUMNS["medication_plans"]
        }]
        with self.assertRaisesRegex(Exception, "references a missing"):
            await backups.preview_restore(_StreamRequest([json.dumps(payload).encode()]))

    async def test_stream_failure_is_not_treated_as_a_complete_backup(self):
        with self.assertRaisesRegex(RuntimeError, "client disconnected"):
            await backups.preview_restore(_FailingStreamRequest())


class BackupDatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_export_uses_repeatable_read_only_transaction(self):
        conn = _connection()
        transaction = _transaction()
        conn.transaction.return_value = transaction
        conn.fetch.return_value = []
        with patch.object(backups, "connection", _manager(conn)):
            response = await backups.export_backup("tasks")

        self.assertEqual("application/json", response.media_type)
        conn.transaction.assert_called_once_with(
            isolation="repeatable_read",
            readonly=True,
        )
        transaction.__aenter__.assert_awaited_once()
        transaction.__aexit__.assert_awaited_once_with(None, None, None)

    async def test_restore_preserves_ids_and_repairs_sequence(self):
        payload = json.dumps(_snapshot()).encode()
        conn = _connection()
        transaction = _transaction()
        conn.transaction.return_value = transaction
        with patch.object(backups, "connection", _manager(conn)):
            result = await backups.restore_backup(_StreamRequest([payload]))

        self.assertEqual("restored", result["status"])
        self.assertEqual(1, result["total_rows"])
        restored = json.loads(conn.executemany.await_args.args[1][0][0])
        self.assertEqual(1, restored["id"])
        self.assertIn("setval", conn.execute.await_args_list[-1].args[0])

    async def test_domain_restore_rejects_pending_ai_proposals(self):
        payload = json.dumps(_snapshot()).encode()
        conn = _connection()
        transaction = _transaction()
        conn.transaction.return_value = transaction
        with patch.object(backups, "connection", _manager(conn)):
            await backups.restore_backup(_StreamRequest([payload]))

        statements = [call.args[0] for call in conn.execute.await_args_list]
        self.assertTrue(
            any(
                "UPDATE ai_action_requests" in statement
                and "status = 'rejected'" in statement
                for statement in statements
            )
        )

    async def test_late_restore_failure_escapes_transaction(self):
        payload = json.dumps(_snapshot()).encode()
        conn = _connection()
        transaction = _transaction()
        conn.transaction.return_value = transaction
        conn.executemany.side_effect = RuntimeError("insert failed")
        with patch.object(backups, "connection", _manager(conn)):
            with self.assertRaisesRegex(RuntimeError, "insert failed"):
                await backups.restore_backup(_StreamRequest([payload]))

        self.assertIs(transaction.__aexit__.await_args.args[0], RuntimeError)


@unittest.skipUnless(
    os.getenv("RUN_DB_TESTS") == "1",
    "Set RUN_DB_TESTS=1 with a running PostgreSQL stack to run integration tests",
)
class BackupIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        while API_PATH in sys.path:
            sys.path.remove(API_PATH)
        sys.path.insert(0, API_PATH)
        from app.db import open_pool
        from app.routers import backups as isolated_backups

        self.backups = isolated_backups
        await open_pool()
        self.medication_name = f"backup-snapshot-{uuid4()}"
        self.task_titles: list[str] = []

    async def asyncTearDown(self):
        from app.db import close_pool, connection

        try:
            async with connection() as conn:
                await conn.execute(
                    "DELETE FROM medications WHERE name=$1",
                    self.medication_name,
                )
                await conn.execute(
                    "DELETE FROM tasks WHERE title=ANY($1::text[])",
                    self.task_titles,
                )
        finally:
            await close_pool()
            while API_PATH in sys.path:
                sys.path.remove(API_PATH)
            for name in list(sys.modules):
                if name == "app" or name.startswith("app."):
                    del sys.modules[name]

    async def test_export_keeps_parent_and_child_from_one_snapshot(self):
        from app.db import connection as database_connection

        async with database_connection() as conn:
            medication_id = await conn.fetchval(
                "INSERT INTO medications(name) VALUES($1) RETURNING id",
                self.medication_name,
            )
            plan_id = await conn.fetchval(
                """INSERT INTO medication_plans(plan_name,medication_id)
                   VALUES($1,$2) RETURNING id""",
                "Snapshot plan",
                medication_id,
            )

        class InterleavingConnection:
            def __init__(self, conn):
                self.conn = conn
                self.read_count = 0

            def transaction(self, *args, **kwargs):
                return self.conn.transaction(*args, **kwargs)

            async def fetch(self, *args):
                rows = await self.conn.fetch(*args)
                self.read_count += 1
                if self.read_count == 1:
                    async with database_connection() as mutation_conn:
                        await mutation_conn.execute(
                            "DELETE FROM medications WHERE id=$1",
                            medication_id,
                        )
                return rows

        @asynccontextmanager
        async def interleaved_connection():
            async with database_connection() as conn:
                yield InterleavingConnection(conn)

        with patch.object(self.backups, "connection", interleaved_connection):
            response = await self.backups.export_backup("medications")

        snapshot = json.loads(response.body)
        self.assertIn(
            medication_id,
            [row["id"] for row in snapshot["tables"]["medications"]],
        )
        self.assertIn(
            plan_id,
            [row["id"] for row in snapshot["tables"]["medication_plans"]],
        )

    async def test_restore_preserves_ids_and_repairs_sequence_for_next_insert(self):
        from app.db import connection as database_connection

        original = await self.backups.export_backup("tasks")
        restored_title = f"backup-restored-{uuid4()}"
        next_title = f"backup-next-{uuid4()}"
        self.task_titles.extend((restored_title, next_title))
        restored_id = 9_000_000
        try:
            result = await self.backups.restore_backup(
                _StreamRequest(
                    [json.dumps(_snapshot(restored_title, restored_id)).encode()]
                )
            )
            self.assertEqual("restored", result["status"])
            async with database_connection() as conn:
                stored_id = await conn.fetchval(
                    "SELECT id FROM tasks WHERE title=$1",
                    restored_title,
                )
                next_id = await conn.fetchval(
                    "INSERT INTO tasks(title) VALUES($1) RETURNING id",
                    next_title,
                )
            self.assertEqual(restored_id, stored_id)
            self.assertGreater(next_id, restored_id)
        finally:
            original_envelope = json.dumps(
                {"snapshot": json.loads(original.body)}
            ).encode()
            await self.backups.restore_backup(_StreamRequest([original_envelope]))

    async def test_late_restore_failure_rolls_back_deleted_rows(self):
        import asyncpg

        from app.db import connection as database_connection

        existing_title = f"backup-existing-{uuid4()}"
        first_title = f"backup-first-{uuid4()}"
        second_title = f"backup-second-{uuid4()}"
        self.task_titles.extend((existing_title, first_title, second_title))
        async with database_connection() as conn:
            await conn.execute(
                "INSERT INTO tasks(title) VALUES($1)",
                existing_title,
            )

        snapshot = _snapshot(first_title, 8_000_000)
        duplicate = dict(snapshot["snapshot"]["tables"]["tasks"][0])
        duplicate["title"] = second_title
        snapshot["snapshot"]["tables"]["tasks"].append(duplicate)
        with self.assertRaises(asyncpg.UniqueViolationError):
            await self.backups.restore_backup(
                _StreamRequest([json.dumps(snapshot).encode()])
            )

        async with database_connection() as conn:
            existing_count = await conn.fetchval(
                "SELECT count(*) FROM tasks WHERE title=$1",
                existing_title,
            )
            failed_count = await conn.fetchval(
                "SELECT count(*) FROM tasks WHERE title=ANY($1::text[])",
                [first_title, second_title],
            )
        self.assertEqual(1, existing_count)
        self.assertEqual(0, failed_count)


if __name__ == "__main__":
    unittest.main()
