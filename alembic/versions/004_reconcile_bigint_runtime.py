"""reconcile the deployed bigint runtime schema

Revision ID: 004_reconcile_bigint_runtime
Revises: 003_drop_activity_logger
Create Date: 2026-08-07

Existing deployments were previously stamped at 003 without ever applying a
schema matching the checked-out API. Re-run the canonical idempotent bootstrap
for bigint databases so those deployments receive the AI contract.
The abandoned UUID redesign is rejected before any reconciliation statement is
executed; converting UUID domain identifiers is a separate, explicit data move.
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "004_reconcile_bigint_runtime"
down_revision = "003_drop_activity_logger"
branch_labels = None
depends_on = None

_INIT_SQL_PATH = Path(__file__).resolve().parents[2] / "database" / "init.sql"


def _split_sql_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    dollar_tag = ""
    in_single_quote = False
    in_double_quote = False
    in_line_comment = False
    block_comment_depth = 0
    index = 0

    while index < len(sql):
        if in_line_comment:
            character = sql[index]
            buffer.append(character)
            index += 1
            if character == "\n":
                in_line_comment = False
            continue

        if block_comment_depth:
            if sql.startswith("/*", index):
                buffer.append("/*")
                block_comment_depth += 1
                index += 2
            elif sql.startswith("*/", index):
                buffer.append("*/")
                block_comment_depth -= 1
                index += 2
            else:
                buffer.append(sql[index])
                index += 1
            continue

        if dollar_tag:
            if sql.startswith(dollar_tag, index):
                buffer.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = ""
            else:
                buffer.append(sql[index])
                index += 1
            continue

        if in_single_quote:
            character = sql[index]
            buffer.append(character)
            index += 1
            if character == "\\" and index < len(sql):
                buffer.append(sql[index])
                index += 1
            elif character == "'":
                if index < len(sql) and sql[index] == "'":
                    buffer.append(sql[index])
                    index += 1
                else:
                    in_single_quote = False
            continue

        if in_double_quote:
            character = sql[index]
            buffer.append(character)
            index += 1
            if character == '"':
                if index < len(sql) and sql[index] == '"':
                    buffer.append(sql[index])
                    index += 1
                else:
                    in_double_quote = False
            continue

        if sql.startswith("--", index):
            buffer.append("--")
            in_line_comment = True
            index += 2
            continue
        if sql.startswith("/*", index):
            buffer.append("/*")
            block_comment_depth = 1
            index += 2
            continue

        if sql[index] == "'":
            buffer.append("'")
            in_single_quote = True
            index += 1
            continue
        if sql[index] == '"':
            buffer.append('"')
            in_double_quote = True
            index += 1
            continue

        if sql[index] == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[index:])
            if match:
                dollar_tag = match.group(0)
                buffer.append(dollar_tag)
                index += len(dollar_tag)
                continue

        character = sql[index]
        if character == ";":
            statement = "".join(buffer).strip()
            if statement and statement.upper() not in {"BEGIN", "COMMIT"}:
                statements.append(statement)
            buffer = []
            index += 1
            continue

        buffer.append(character)
        index += 1

    if dollar_tag or in_single_quote or in_double_quote or block_comment_depth:
        raise ValueError("Unterminated quoted string or comment in init.sql")

    tail = "".join(buffer).strip()
    if tail and tail.upper() not in {"BEGIN", "COMMIT"}:
        statements.append(tail)
    return statements


def _assert_bigint_runtime() -> None:
    tasks_id_type = op.get_bind().execute(
        text(
            """
            SELECT data_type
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'tasks'
               AND column_name = 'id'
            """
        )
    ).scalar_one_or_none()
    if tasks_id_type != "bigint":
        actual = tasks_id_type or "missing"
        raise RuntimeError(
            "Cannot reconcile this OmniFlow database: "
            f"tasks.id is {actual}, expected bigint. The prior UUID redesign "
            "requires an explicit data migration and must not be mixed with the "
            "runtime schema."
        )


def upgrade() -> None:
    _assert_bigint_runtime()
    sql = _INIT_SQL_PATH.read_text(encoding="utf-8")
    for statement in _split_sql_statements(sql):
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError(
        "004 reconciles deployed data in place and is intentionally irreversible"
    )
