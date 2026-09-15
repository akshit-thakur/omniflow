"""Portable, module-scoped JSON backups.

Backups are snapshots of durable domain tables.  Derived search embeddings and
the AI mutation audit are intentionally excluded: the former can be rebuilt,
and the latter is not needed to restore the user's working data.
"""

from datetime import date, datetime, time, timezone
from decimal import Decimal
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response

from ..db import connection


router = APIRouter(prefix="/backups", tags=["backups"])

BACKUP_FORMAT = "omniflow-backup"
BACKUP_VERSION = 1
MAX_RESTORE_BYTES = 250 * 1024 * 1024

# These are API-owned constants.  They are deliberately the only identifiers
# composed into SQL below.
MODULE_TABLES: dict[str, tuple[str, ...]] = {
    "tasks": ("tasks",),
    "medications": (
        "medications",
        "medication_plans",
        "medication_plan_times",
        "medication_logs",
    ),
    "gym": (
        "exercise_catalog",
        "training_sets",
        "training_set_exercises",
        "workout_sessions",
        "workout_session_exercises",
    ),
    "kitchen": (
        "ingredients",
        "recipes",
        "recipe_ingredients",
        "inventory",
        "meal_entries",
    ),
    "media": ("media_items",),
    "ai": (
        "ai_action_requests",
        "ai_action_proposals",
        "ai_mutation_audit",
    ),
}
MODULE_TABLES["all"] = tuple(table for tables in MODULE_TABLES.values() for table in tables)

TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "tasks": ("id", "title", "description", "priority", "completed", "due_date", "created_at", "updated_at", "completion_date"),
    "medications": ("id", "name", "common_dosage", "notes", "created_at", "updated_at"),
    "medication_plans": ("id", "plan_name", "medication_id", "dosage", "notes", "active", "created_at", "updated_at"),
    "medication_plan_times": ("id", "plan_id", "schedule_time", "created_at", "updated_at"),
    "medication_logs": ("id", "plan_id", "taken_at", "scheduled_time", "notes", "created_at", "updated_at"),
    "exercise_catalog": ("id", "name", "muscle_group", "equipment", "description", "created_at", "updated_at"),
    "training_sets": ("id", "name", "description", "created_at", "updated_at"),
    "training_set_exercises": ("id", "training_set_id", "exercise_id", "order_index", "created_at", "updated_at"),
    "workout_sessions": ("id", "training_set_id", "set_name", "session_date", "duration_minutes", "notes", "created_at", "updated_at"),
    "workout_session_exercises": ("id", "workout_session_id", "exercise_id", "exercise_name", "sets_completed", "reps_completed", "weight_kg", "details", "created_at", "updated_at"),
    "ingredients": ("id", "name", "category", "default_unit", "created_at", "updated_at"),
    "recipes": ("id", "name", "description", "instructions", "difficulty", "prep_time_minutes", "created_at", "updated_at"),
    "recipe_ingredients": ("recipe_id", "ingredient_id", "quantity", "unit", "created_at", "updated_at"),
    "inventory": ("id", "ingredient_id", "quantity", "unit", "expiry_date", "min_quantity", "created_at", "updated_at"),
    "meal_entries": ("id", "meal_date", "meal_type", "recipe_id", "notes", "created_at", "updated_at"),
    "media_items": ("id", "title", "media_type", "status", "author_creator", "release_year", "genre", "progress_current", "progress_total", "is_favorite", "rating", "notes", "review", "completion_date", "created_at", "updated_at"),
    "ai_action_requests": ("request_id", "status", "context", "review", "review_digest", "decided_by", "proposed_at", "decided_at"),
    "ai_action_proposals": ("request_id", "action_index", "action", "arguments"),
    "ai_mutation_audit": ("id", "request_id", "action_index", "action", "entity_table", "entity_id", "arguments", "before_state", "after_state", "status", "error", "created_at"),
}

JSON_COLUMNS: dict[str, tuple[str, ...]] = {
    "workout_session_exercises": ("details",),
    "ai_action_requests": ("context",),
    "ai_action_proposals": ("arguments",),
    "ai_mutation_audit": ("arguments", "before_state", "after_state"),
}
JSON_COLUMNS["ai_action_requests"] = ("context", "review")

NUMERIC_COLUMNS: dict[str, tuple[int, int, bool]] = {
    "recipe_ingredients.quantity": (10, 2, True),
    "inventory.quantity": (10, 2, True),
    "inventory.min_quantity": (10, 2, True),
    "workout_session_exercises.weight_kg": (8, 2, True),
}

DELETE_ORDER = tuple(reversed(MODULE_TABLES["all"]))
INSERT_ORDER = MODULE_TABLES["all"]

_DATE_COLUMNS = {
    "tasks": {"due_date"},
    "workout_sessions": {"session_date"},
    "inventory": {"expiry_date"},
    "meal_entries": {"meal_date"},
}
_TIME_COLUMNS = {
    "medication_plan_times": {"schedule_time"},
    "medication_logs": {"scheduled_time"},
}
_DATETIME_COLUMNS = {
    table: {column for column in columns if column.endswith("_at") or column.endswith("_date")}
    for table, columns in TABLE_COLUMNS.items()
}
_DATETIME_COLUMNS["tasks"].discard("due_date")
_DATETIME_COLUMNS["workout_sessions"].discard("session_date")
_DATETIME_COLUMNS["inventory"].discard("expiry_date")
_DATETIME_COLUMNS["meal_entries"].discard("meal_date")
_DATETIME_COLUMNS["media_items"].discard("completion_date")
_DATETIME_COLUMNS["tasks"].add("completion_date")
_DATETIME_COLUMNS["media_items"].add("completion_date")
_UUID_COLUMNS = {
    "ai_action_requests": {"request_id"},
    "ai_action_proposals": {"request_id"},
    "ai_mutation_audit": {"request_id"},
}
_FOREIGN_KEYS = (
    ("medication_plans", "medication_id", "medications", "id"),
    ("medication_plan_times", "plan_id", "medication_plans", "id"),
    ("medication_logs", "plan_id", "medication_plans", "id"),
    ("training_set_exercises", "training_set_id", "training_sets", "id"),
    ("training_set_exercises", "exercise_id", "exercise_catalog", "id"),
    ("workout_sessions", "training_set_id", "training_sets", "id"),
    ("workout_session_exercises", "workout_session_id", "workout_sessions", "id"),
    ("workout_session_exercises", "exercise_id", "exercise_catalog", "id"),
    ("recipe_ingredients", "recipe_id", "recipes", "id"),
    ("recipe_ingredients", "ingredient_id", "ingredients", "id"),
    ("inventory", "ingredient_id", "ingredients", "id"),
    ("meal_entries", "recipe_id", "recipes", "id"),
    ("ai_action_proposals", "request_id", "ai_action_requests", "request_id"),
    ("ai_mutation_audit", "request_id", "ai_action_requests", "request_id"),
)


def _json_default(value: Any) -> str:
    if isinstance(value, (date, time, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Unsupported backup value: {type(value)!r}")


def _validate_snapshot_value(table_name: str, column: str, value: Any) -> None:
    if value is None:
        return
    try:
        numeric = NUMERIC_COLUMNS.get(f"{table_name}.{column}")
        if numeric:
            if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
                raise ValueError("must be a decimal string or number")
            decimal = Decimal(str(value))
            precision, scale, nonnegative = numeric
            if not decimal.is_finite() or (nonnegative and decimal < 0):
                raise ValueError("must be finite and in range")
            digits = len(decimal.as_tuple().digits)
            if digits > precision or -decimal.as_tuple().exponent > scale:
                raise ValueError("has too many digits")
        elif column in _DATE_COLUMNS.get(table_name, set()):
            if not isinstance(value, str):
                raise ValueError("must be an ISO date string")
            date.fromisoformat(value)
        elif column in _TIME_COLUMNS.get(table_name, set()):
            if not isinstance(value, str):
                raise ValueError("must be an ISO time string")
            time.fromisoformat(value)
        elif column in _DATETIME_COLUMNS.get(table_name, set()):
            if not isinstance(value, str):
                raise ValueError("must be an ISO datetime string")
            datetime.fromisoformat(value)
        elif column in _UUID_COLUMNS.get(table_name, set()):
            if not isinstance(value, str):
                raise ValueError("must be a UUID string")
            UUID(value)
    except (TypeError, ValueError, ArithmeticError) as exc:
        raise _backup_error(f"Backup value {table_name}.{column} is invalid") from exc


def _validate_snapshot_relationships(module: str, tables: dict[str, Any]) -> None:
    selected_tables = set(MODULE_TABLES[module])
    for child_table, child_column, parent_table, parent_column in _FOREIGN_KEYS:
        if child_table not in selected_tables or parent_table not in selected_tables:
            continue
        parent_values = {
            row[parent_column]
            for row in tables[parent_table]
            if row.get(parent_column) is not None
        }
        for row in tables[child_table]:
            value = row.get(child_column)
            if value is not None and value not in parent_values:
                raise _backup_error(
                    f"Backup row {child_table}.{child_column} references a missing {parent_table} row"
                )


def _backup_error(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


async def _read_restore_body(request: Request) -> bytes:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > MAX_RESTORE_BYTES:
            raise HTTPException(status_code=413, detail="Backup file is too large")
        body.extend(chunk)
    return bytes(body)


def _parse_snapshot(raw_body: bytes) -> dict[str, Any]:
    if len(raw_body) > MAX_RESTORE_BYTES:
        raise HTTPException(status_code=413, detail="Backup file is too large")
    try:
        envelope = json.loads(
            raw_body.decode("utf-8"), parse_float=Decimal,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"unsupported numeric constant {value}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _backup_error("Backup file must be valid UTF-8 JSON") from exc
    if not isinstance(envelope, dict) or set(envelope) != {"snapshot"}:
        raise _backup_error("Restore request must contain only a snapshot")
    snapshot = envelope["snapshot"]
    if not isinstance(snapshot, dict):
        raise _backup_error("Backup snapshot must be an object")
    if snapshot.get("format") != BACKUP_FORMAT or snapshot.get("version") != BACKUP_VERSION:
        raise _backup_error("This is not a compatible Omniflow backup")
    module = snapshot.get("module")
    tables = snapshot.get("tables")
    if module not in MODULE_TABLES or not isinstance(tables, dict):
        raise _backup_error("Backup module or table data is invalid")
    expected_tables = MODULE_TABLES[module]
    if set(tables) != set(expected_tables):
        raise _backup_error("Backup tables do not match its module")
    for table_name in expected_tables:
        rows = tables[table_name]
        if not isinstance(rows, list):
            raise _backup_error(f"Backup table {table_name} must be a list")
        expected_columns = set(TABLE_COLUMNS[table_name])
        for row in rows:
            if not isinstance(row, dict) or set(row) != expected_columns:
                raise _backup_error(f"Backup rows for {table_name} do not match this app version")
            for column, value in row.items():
                _validate_snapshot_value(table_name, column, value)
            for column in JSON_COLUMNS.get(table_name, ()):
                value = row[column]
                if value is not None:
                    allowed_shape = "array" if (table_name, column) == ("workout_session_exercises", "details") else "object"
                    if (allowed_shape == "array" and not isinstance(value, list)) or (allowed_shape == "object" and not isinstance(value, dict)):
                        raise _backup_error(f"Backup value {table_name}.{column} must be an {allowed_shape} or null")
    _validate_snapshot_relationships(module, tables)
    return snapshot


def _snapshot_summary(snapshot: dict[str, Any]) -> dict[str, Any]:
    tables = snapshot["tables"]
    return {
        "module": snapshot["module"],
        "exported_at": snapshot.get("exported_at"),
        "row_counts": {table: len(rows) for table, rows in tables.items()},
        "total_rows": sum(len(rows) for rows in tables.values()),
    }


def _export_row(table_name: str, row: Any) -> dict[str, Any]:
    exported = dict(row)
    for column in JSON_COLUMNS.get(table_name, ()):
        value = exported[column]
        if isinstance(value, str):
            exported[column] = json.loads(value)
    return exported


@router.get("/export/{module}")
async def export_backup(module: str):
    if module not in MODULE_TABLES:
        raise HTTPException(status_code=404, detail="Unknown backup module")

    tables: dict[str, list[Any]] = {}
    async with connection() as conn:
        async with conn.transaction(isolation="repeatable_read", readonly=True):
            for table_name in MODULE_TABLES[module]:
                columns = ", ".join(TABLE_COLUMNS[table_name])
                order_by = ", ".join(TABLE_COLUMNS[table_name][:1])
                rows = await conn.fetch(
                    f"SELECT {columns} FROM {table_name} ORDER BY {order_by}"
                )
                tables[table_name] = [_export_row(table_name, row) for row in rows]

    snapshot = {
        "format": BACKUP_FORMAT,
        "version": BACKUP_VERSION,
        "module": module,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "row_counts": {table: len(rows) for table, rows in tables.items()},
        "tables": tables,
    }
    filename = f"omniflow-{module}-{datetime.now(timezone.utc).date().isoformat()}.json"
    return Response(
        content=json.dumps(snapshot, default=_json_default, separators=(",", ":")),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore/preview")
async def preview_restore(request: Request):
    return _snapshot_summary(_parse_snapshot(await _read_restore_body(request)))


@router.post("/restore")
async def restore_backup(request: Request):
    snapshot = _parse_snapshot(await _read_restore_body(request))
    module = snapshot["module"]
    tables = snapshot["tables"]
    selected_tables = set(MODULE_TABLES[module])
    delete_order = [table for table in DELETE_ORDER if table in selected_tables]
    insert_order = [table for table in INSERT_ORDER if table in selected_tables]

    async with connection() as conn:
        async with conn.transaction():
            for table_name in delete_order:
                await conn.execute(f"DELETE FROM {table_name}")
            for table_name in insert_order:
                columns = TABLE_COLUMNS[table_name]
                column_sql = ", ".join(columns)
                select_sql = ", ".join(columns)
                rows = tables[table_name]
                if rows:
                    await conn.executemany(
                        f"INSERT INTO {table_name} ({column_sql}) "
                        f"SELECT {select_sql} FROM jsonb_populate_record(NULL::{table_name}, $1::jsonb)",
                        [
                            (json.dumps(row, default=_json_default, separators=(",", ":")),)
                            for row in rows
                        ],
                    )
            if module != "ai":
                # A restore replaces the domain rows that pending proposals may
                # reference.  Invalidate those proposals before leaving the
                # transaction so they cannot be approved against restored IDs.
                await conn.execute(
                    "UPDATE ai_action_requests "
                    "SET status = 'rejected', decided_at = NOW() "
                    "WHERE status = 'pending'"
                )
            for table_name in insert_order:
                if "id" in TABLE_COLUMNS[table_name]:
                    await conn.execute(
                        f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                        f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), "
                        f"EXISTS(SELECT 1 FROM {table_name}))"
                    )

    return {"status": "restored", **_snapshot_summary(snapshot)}
