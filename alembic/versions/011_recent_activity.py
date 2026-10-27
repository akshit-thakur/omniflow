"""Transactional activity for manual changes and restores, alongside AI audit."""
from alembic import op

revision = "011_recent_activity"
down_revision = "010_finite_numeric_constraints"
branch_labels = None
depends_on = None

TABLES = ('tasks', 'medications', 'medication_plans', 'medication_plan_times',
          'medication_logs', 'exercise_catalog', 'training_sets', 'training_set_exercises',
          'workout_sessions', 'workout_session_exercises', 'ingredients', 'recipes',
          'recipe_ingredients', 'inventory', 'meal_entries', 'media_items')


def upgrade():
    op.execute("""
        CREATE TABLE activity_events (
            id BIGSERIAL PRIMARY KEY,
            created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
            source TEXT NOT NULL, action TEXT NOT NULL,
            entity_table TEXT NOT NULL, entity_id TEXT, label TEXT
        );
        CREATE INDEX activity_events_time ON activity_events(created_at DESC);
        CREATE FUNCTION record_activity() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE row_data jsonb; source_name text;
        BEGIN
            source_name := COALESCE(NULLIF(current_setting('omniflow.source', true), ''), 'manual');
            IF source_name = 'ai' THEN RETURN NULL; END IF;
            IF TG_OP = 'UPDATE' AND OLD IS NOT DISTINCT FROM NEW THEN RETURN NULL; END IF;
            IF TG_OP = 'DELETE' THEN row_data := to_jsonb(OLD); ELSE row_data := to_jsonb(NEW); END IF;
            INSERT INTO activity_events(source, action, entity_table, entity_id, label)
            VALUES (source_name, lower(TG_OP), TG_TABLE_NAME,
                COALESCE(row_data->>'id', concat_ws(':', row_data->>'recipe_id', row_data->>'ingredient_id')),
                COALESCE(row_data->>'title', row_data->>'name', row_data->>'plan_name', row_data->>'set_name', row_data->>'id'));
            RETURN NULL;
        END $$;
    """)
    for table in TABLES:
        op.execute(f'CREATE TRIGGER activity_change AFTER INSERT OR UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION record_activity()')


def downgrade():
    for table in TABLES:
        op.execute(f'DROP TRIGGER IF EXISTS activity_change ON {table}')
    op.execute('DROP FUNCTION record_activity()')
    op.execute('DROP TABLE activity_events')
