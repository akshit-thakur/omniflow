"""initial schema

OmniFlow PostgreSQL baseline schema sourced from database/init.sql.

Creates the bigint-ID runtime schema plus retrieval and audit tables used by the
API, AI service, and web client.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-08-06
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic import op

revision = "001_initial_schema"
down_revision = None
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


def _load_init_sql_statements() -> list[str]:
    sql = _INIT_SQL_PATH.read_text(encoding="utf-8")
    return _split_sql_statements(sql)


def upgrade() -> None:
    for statement in _load_init_sql_statements():
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sync_mutations CASCADE")
    op.execute("DROP TABLE IF EXISTS sync_tombstones CASCADE")
    op.execute("DROP TABLE IF EXISTS sync_state CASCADE")
    op.execute("DROP TABLE IF EXISTS ai_mutation_audit CASCADE")
    op.execute("DROP TABLE IF EXISTS ai_action_proposals CASCADE")
    op.execute("DROP TABLE IF EXISTS ai_action_requests CASCADE")
    op.execute("DROP TABLE IF EXISTS ai_entity_embeddings CASCADE")
    op.execute("DROP TABLE IF EXISTS media_items CASCADE")
    op.execute("DROP TABLE IF EXISTS meal_entries CASCADE")
    op.execute("DROP TABLE IF EXISTS inventory CASCADE")
    op.execute("DROP TABLE IF EXISTS recipe_ingredients CASCADE")
    op.execute("DROP TABLE IF EXISTS recipes CASCADE")
    op.execute("DROP TABLE IF EXISTS ingredients CASCADE")
    op.execute("DROP TABLE IF EXISTS workout_session_exercises CASCADE")
    op.execute("DROP TABLE IF EXISTS workout_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS training_set_exercises CASCADE")
    op.execute("DROP TABLE IF EXISTS training_sets CASCADE")
    op.execute("DROP TABLE IF EXISTS exercise_catalog CASCADE")
    op.execute("DROP TABLE IF EXISTS medication_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS medication_plan_times CASCADE")
    op.execute("DROP TABLE IF EXISTS medication_plans CASCADE")
    op.execute("DROP TABLE IF EXISTS medications CASCADE")
    op.execute("DROP TABLE IF EXISTS focus_tracking_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS tasks CASCADE")
    op.execute("DROP FUNCTION IF EXISTS record_sync_tombstone()")
    op.execute("DROP FUNCTION IF EXISTS set_sync_columns()")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
    op.execute("DROP EXTENSION IF EXISTS vector")
