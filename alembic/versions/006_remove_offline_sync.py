"""remove offline sync protocol

Revision ID: 006_remove_offline_sync
Revises: 005_drop_focus_tracking_sessions
Create Date: 2026-08-19

The current product is optimized for the single browser app. The server-side
offline device sync protocol is not part of the active product surface.
"""

from alembic import op

revision = "006_remove_offline_sync"
down_revision = "005_drop_focus_tracking_sessions"
branch_labels = None
depends_on = None


SYNC_TABLES = (
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
)


def upgrade() -> None:
    # Pre-Alembic volumes can still have retired tables (finance, planner,
    # habits, timeboxing) whose sync triggers block DROP FUNCTION.
    op.execute(
        """
        DO $$
        DECLARE
            rec RECORD;
        BEGIN
            FOR rec IN
                SELECT c.relname AS table_name, t.tgname
                  FROM pg_trigger t
                  JOIN pg_class c ON c.oid = t.tgrelid
                  JOIN pg_proc p ON p.oid = t.tgfoid
                  JOIN pg_namespace n ON n.oid = c.relnamespace
                 WHERE n.nspname = current_schema()
                   AND NOT t.tgisinternal
                   AND p.proname IN ('set_sync_columns', 'record_sync_tombstone')
            LOOP
                EXECUTE format(
                    'DROP TRIGGER IF EXISTS %I ON %I',
                    rec.tgname,
                    rec.table_name
                );
            END LOOP;
        END;
        $$;
        """
    )
    op.execute("DROP TABLE IF EXISTS finance_transactions CASCADE")

    for table_name in SYNC_TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS trg_{table_name}_sync ON "{table_name}"')
        op.execute(f'DROP TRIGGER IF EXISTS trg_{table_name}_tombstone ON "{table_name}"')
        op.execute(f'DROP INDEX IF EXISTS idx_{table_name}_change')

    for table_name in SYNC_TABLES:
        op.execute(f'ALTER TABLE "{table_name}" DROP COLUMN IF EXISTS change_xid')

    for table_name in set(SYNC_TABLES) - {"recipe_ingredients"}:
        op.execute(f'DROP INDEX IF EXISTS uq_{table_name}_client_id')
        op.execute(f'ALTER TABLE "{table_name}" DROP COLUMN IF EXISTS client_id')

    op.execute("DROP TABLE IF EXISTS sync_mutations CASCADE")
    op.execute("DROP TABLE IF EXISTS sync_tombstones CASCADE")
    op.execute("DROP TABLE IF EXISTS sync_state CASCADE")
    op.execute("DROP FUNCTION IF EXISTS record_sync_tombstone()")
    op.execute("DROP FUNCTION IF EXISTS set_sync_columns()")


def downgrade() -> None:
    raise NotImplementedError(
        "Offline sync was removed from the active product surface; "
        "restore it from revision 005 if needed."
    )
