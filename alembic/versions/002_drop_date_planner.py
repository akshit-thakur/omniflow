"""drop date planner tables

Remove date_activities and date_retrospectives from legacy databases.

Revision ID: 002_drop_date_planner
Revises: 001_initial_schema
Create Date: 2026-08-07
"""

from __future__ import annotations

from alembic import op

revision = "002_drop_date_planner"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS date_retrospectives CASCADE")
    op.execute("DROP TABLE IF EXISTS date_activities CASCADE")


def downgrade() -> None:
    raise RuntimeError(
        "Date Planner was removed with its code and data; revision 002 is "
        "intentionally irreversible"
    )
