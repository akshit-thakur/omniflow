"""drop activity logger tables

Remove habits, habit_logs, and sleep_logs from legacy databases.

Revision ID: 003_drop_activity_logger
Revises: 002_drop_date_planner
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op

revision = "003_drop_activity_logger"
down_revision = "002_drop_date_planner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS habit_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS habits CASCADE")
    op.execute("DROP TABLE IF EXISTS sleep_logs CASCADE")


def downgrade() -> None:
    raise RuntimeError(
        "Activity Logger was removed with its code and data; revision 003 is "
        "intentionally irreversible"
    )
