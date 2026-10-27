"""Prepare a previous-schema fixture in an explicitly disposable test database."""
import argparse
import asyncio
from alembic.config import Config
from alembic import command
from api.app import db


async def seed():
    await db.open_pool()
    try:
        async with db.connection() as conn:
            assert await conn.fetchval('SELECT version_num FROM alembic_version') == '010_finite_numeric_constraints'
            await conn.execute("INSERT INTO tasks(title) VALUES('Lifecycle retained task')")
    finally:
        await db.close_pool()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--disposable', action='store_true', required=True)
    parser.parse_args()
    command.downgrade(Config('alembic.ini'), '010_finite_numeric_constraints')
    asyncio.run(seed())
    print('Previous-schema fixture ready; run normal database-init to upgrade')
