"""drop focus tracking sessions

Revision ID: 005_drop_focus_tracking_sessions
Revises: 004_reconcile_bigint_runtime
Create Date: 2026-08-19

The current product keeps tasks as a plain todo list. Focus/timebox sessions are
not consumed by the frontend and are no longer part of the active domain model.
"""

from alembic import op

revision = "005_drop_focus_tracking_sessions"
down_revision = "004_reconcile_bigint_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.sync_tombstones') IS NOT NULL THEN
                EXECUTE 'DELETE FROM sync_tombstones
                          WHERE source_table = ''focus_tracking_sessions''';
            END IF;
        END;
        $$;
        """
    )
    op.execute("DROP TABLE IF EXISTS focus_tracking_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS timeboxing_sessions CASCADE")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS focus_tracking_sessions (
            id BIGSERIAL PRIMARY KEY,
            task_id BIGINT REFERENCES tasks(id) ON DELETE SET NULL,
            duration_minutes INTEGER CHECK (duration_minutes IS NULL OR duration_minutes >= 0),
            start_time TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMPTZ,
            status TEXT NOT NULL DEFAULT 'planned',
            notes TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            change_xid XID8 NOT NULL DEFAULT pg_current_xact_id(),
            client_id UUID,
            CONSTRAINT chk_focus_tracking_status
                CHECK (status IN ('planned','active','paused','completed','incomplete','cancelled')),
            CONSTRAINT chk_focus_tracking_time_order
                CHECK (end_time IS NULL OR end_time >= start_time)
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_focus_tracking
            ON focus_tracking_sessions ((TRUE))
            WHERE status IN ('active','paused')
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_tracking_task ON focus_tracking_sessions(task_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_focus_tracking_start ON focus_tracking_sessions(start_time DESC)"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_focus_tracking_sessions_client_id
            ON focus_tracking_sessions(client_id) WHERE client_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_focus_tracking_sessions_change
            ON focus_tracking_sessions(change_xid,id)
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_focus_tracking_sessions_updated_at
            BEFORE UPDATE ON focus_tracking_sessions
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_focus_tracking_sessions_sync
            BEFORE INSERT OR UPDATE ON focus_tracking_sessions
            FOR EACH ROW EXECUTE FUNCTION set_sync_columns()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_focus_tracking_sessions_tombstone
            AFTER DELETE ON focus_tracking_sessions
            FOR EACH ROW EXECUTE FUNCTION record_sync_tombstone('id')
        """
    )
