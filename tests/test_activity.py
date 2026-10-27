import os
import unittest
from uuid import uuid4


@unittest.skipUnless(os.getenv('RUN_DB_TESTS') == '1', 'Requires isolated PostgreSQL')
class ActivityIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from api.app import db
        self.db = db
        await db.open_pool()

    async def asyncTearDown(self):
        await self.db.close_pool()

    async def test_activity_rolls_back_with_the_record(self):
        title = f'rollback-{uuid4()}'
        async with self.db.connection() as conn:
            with self.assertRaisesRegex(RuntimeError, 'rollback'):
                async with conn.transaction():
                    await conn.execute('INSERT INTO tasks(title) VALUES($1)', title)
                    self.assertEqual(1, await conn.fetchval('SELECT count(*) FROM activity_events WHERE label=$1', title))
                    raise RuntimeError('rollback')
            self.assertEqual(0, await conn.fetchval('SELECT count(*) FROM activity_events WHERE label=$1', title))
            self.assertEqual(0, await conn.fetchval('SELECT count(*) FROM tasks WHERE title=$1', title))

    async def test_source_is_reset_between_connections_and_ai_uses_its_own_audit(self):
        title = f'sources-{uuid4()}'
        ids = []
        try:
            for source in ('restore', 'ai', 'manual'):
                token = self.db.activity_source.set(source)
                try:
                    async with self.db.connection() as conn:
                        ids.append(await conn.fetchval('INSERT INTO tasks(title) VALUES($1) RETURNING id', title))
                finally:
                    self.db.activity_source.reset(token)
            async with self.db.connection() as conn:
                events = await conn.fetch('SELECT source FROM activity_events WHERE label=$1 ORDER BY id', title)
                self.assertEqual(['restore', 'manual'], [row['source'] for row in events])
                self.assertEqual('manual', await conn.fetchval("SELECT current_setting('omniflow.source')"))
        finally:
            async with self.db.connection() as conn:
                await conn.execute('DELETE FROM tasks WHERE id=ANY($1::bigint[])', ids)
                await conn.execute('DELETE FROM activity_events WHERE label=$1', title)
