-- Canonical OmniFlow PostgreSQL schema.
--
-- The running application uses bigint domain identifiers.  This script is both
-- the fresh-install target (Alembic 001) and the idempotent reconciliation used
-- by Alembic 004 for pre-Alembic bigint databases.  It deliberately refuses to
-- combine the abandoned UUID redesign with the bigint runtime contract.

CREATE EXTENSION IF NOT EXISTS vector;

DO $$
DECLARE
    tasks_id_type TEXT;
BEGIN
    SELECT data_type
      INTO tasks_id_type
      FROM information_schema.columns
     WHERE table_schema = current_schema()
       AND table_name = 'tasks'
       AND column_name = 'id';

    IF tasks_id_type IS NOT NULL AND tasks_id_type <> 'bigint' THEN
        RAISE EXCEPTION
            'Unsupported OmniFlow schema: tasks.id is %, expected bigint. The prior UUID redesign cannot be mixed with the runtime schema.',
            tasks_id_type;
    END IF;

    IF to_regclass('public.ai_index_entries') IS NOT NULL
       AND to_regclass('public.ai_entity_embeddings') IS NULL THEN
        ALTER TABLE ai_index_entries RENAME TO ai_entity_embeddings;
    ELSIF to_regclass('public.ai_index_entries') IS NOT NULL
          AND to_regclass('public.ai_entity_embeddings') IS NOT NULL THEN
        RAISE EXCEPTION
            'Both ai_index_entries and ai_entity_embeddings exist; merge them explicitly before migrating.';
    END IF;
END;
$$;

-- Revisions 002/003 may have been skipped by the old "stamp head" path.
DROP TABLE IF EXISTS date_retrospectives CASCADE;
DROP TABLE IF EXISTS date_activities CASCADE;
DROP TABLE IF EXISTS habit_logs CASCADE;
DROP TABLE IF EXISTS habits CASCADE;
DROP TABLE IF EXISTS sleep_logs CASCADE;
DROP TABLE IF EXISTS timeboxing_sessions CASCADE;
DROP TABLE IF EXISTS focus_tracking_sessions CASCADE;
DROP TABLE IF EXISTS finance_transactions CASCADE;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$;

CREATE TABLE IF NOT EXISTS tasks (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL
        CONSTRAINT chk_tasks_title_length
        CHECK (char_length(btrim(title)) BETWEEN 1 AND 500),
    description TEXT,
    priority TEXT NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('low', 'medium', 'high')),
    completed BOOLEAN NOT NULL DEFAULT FALSE,
    due_date DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completion_date TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority);
CREATE INDEX IF NOT EXISTS idx_tasks_due_date ON tasks(due_date) WHERE due_date IS NOT NULL;

CREATE TABLE IF NOT EXISTS medications (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
        CONSTRAINT chk_medications_name_length
        CHECK (char_length(btrim(name)) BETWEEN 1 AND 200),
    common_dosage TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS medication_plans (
    id BIGSERIAL PRIMARY KEY,
    plan_name TEXT NOT NULL
        CONSTRAINT chk_medication_plans_name_length
        CHECK (char_length(btrim(plan_name)) BETWEEN 1 AND 200),
    medication_id BIGINT NOT NULL REFERENCES medications(id) ON DELETE CASCADE,
    dosage TEXT,
    notes TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS medication_plan_times (
    id BIGSERIAL PRIMARY KEY,
    plan_id BIGINT NOT NULL REFERENCES medication_plans(id) ON DELETE CASCADE,
    schedule_time TIME NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (plan_id, schedule_time)
);

CREATE TABLE IF NOT EXISTS medication_logs (
    id BIGSERIAL PRIMARY KEY,
    plan_id BIGINT NOT NULL REFERENCES medication_plans(id) ON DELETE CASCADE,
    taken_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    scheduled_time TIME,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_medication_plans_medication
    ON medication_plans(medication_id);
CREATE INDEX IF NOT EXISTS idx_medication_logs_taken_at
    ON medication_logs(taken_at DESC);

CREATE TABLE IF NOT EXISTS exercise_catalog (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
        CONSTRAINT chk_exercise_catalog_name_length
        CHECK (char_length(btrim(name)) BETWEEN 1 AND 200),
    muscle_group TEXT NOT NULL
        CONSTRAINT chk_exercise_catalog_muscle_group_length
        CHECK (char_length(btrim(muscle_group)) BETWEEN 1 AND 100),
    equipment TEXT,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS training_sets (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL
        CONSTRAINT chk_training_sets_name_length
        CHECK (char_length(btrim(name)) BETWEEN 1 AND 200),
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS training_set_exercises (
    id BIGSERIAL PRIMARY KEY,
    training_set_id BIGINT NOT NULL REFERENCES training_sets(id) ON DELETE CASCADE,
    exercise_id BIGINT NOT NULL REFERENCES exercise_catalog(id) ON DELETE RESTRICT,
    order_index INTEGER NOT NULL DEFAULT 0
        CONSTRAINT chk_training_set_exercises_order
        CHECK (order_index >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (training_set_id, exercise_id)
);

CREATE TABLE IF NOT EXISTS workout_sessions (
    id BIGSERIAL PRIMARY KEY,
    training_set_id BIGINT REFERENCES training_sets(id) ON DELETE SET NULL,
    set_name TEXT NOT NULL,
    session_date DATE NOT NULL,
    duration_minutes INTEGER CHECK (duration_minutes IS NULL OR duration_minutes >= 0),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS workout_session_exercises (
    id BIGSERIAL PRIMARY KEY,
    workout_session_id BIGINT NOT NULL REFERENCES workout_sessions(id) ON DELETE CASCADE,
    exercise_id BIGINT REFERENCES exercise_catalog(id) ON DELETE SET NULL,
    exercise_name TEXT NOT NULL,
    sets_completed INTEGER NOT NULL DEFAULT 0 CHECK (sets_completed >= 0),
    reps_completed INTEGER CHECK (reps_completed IS NULL OR reps_completed >= 0),
    weight_kg NUMERIC(8, 2) CHECK (weight_kg IS NULL OR weight_kg >= 0),
    details JSONB NOT NULL DEFAULT '[]'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_training_set_exercises_set
    ON training_set_exercises(training_set_id, order_index);
CREATE INDEX IF NOT EXISTS idx_workout_sessions_date
    ON workout_sessions(session_date DESC);
CREATE INDEX IF NOT EXISTS idx_workout_session_exercises_session
    ON workout_session_exercises(workout_session_id);

CREATE TABLE IF NOT EXISTS ingredients (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
        CONSTRAINT chk_ingredients_name_length
        CHECK (char_length(btrim(name)) BETWEEN 1 AND 200),
    category TEXT NOT NULL DEFAULT 'Other',
    default_unit TEXT NOT NULL DEFAULT 'piece',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recipes (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL
        CONSTRAINT chk_recipes_name_length
        CHECK (char_length(btrim(name)) BETWEEN 1 AND 300),
    description TEXT,
    instructions TEXT,
    difficulty TEXT CHECK (difficulty IS NULL OR difficulty IN ('Easy', 'Medium', 'Hard')),
    prep_time_minutes INTEGER CHECK (prep_time_minutes IS NULL OR prep_time_minutes >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recipe_ingredients (
    recipe_id BIGINT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    ingredient_id BIGINT NOT NULL REFERENCES ingredients(id) ON DELETE CASCADE,
    quantity NUMERIC(10, 2) NOT NULL CHECK (quantity >= 0),
    unit TEXT NOT NULL
        CONSTRAINT chk_recipe_ingredients_unit_length
        CHECK (char_length(btrim(unit)) BETWEEN 1 AND 50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (recipe_id, ingredient_id)
);

CREATE TABLE IF NOT EXISTS inventory (
    id BIGSERIAL PRIMARY KEY,
    ingredient_id BIGINT NOT NULL UNIQUE REFERENCES ingredients(id) ON DELETE CASCADE,
    quantity NUMERIC(10, 2) NOT NULL CHECK (quantity >= 0),
    unit TEXT NOT NULL
        CONSTRAINT chk_inventory_unit_length
        CHECK (char_length(btrim(unit)) BETWEEN 1 AND 50),
    expiry_date DATE,
    min_quantity NUMERIC(10, 2) NOT NULL DEFAULT 0 CHECK (min_quantity >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS meal_entries (
    id BIGSERIAL PRIMARY KEY,
    meal_date DATE NOT NULL,
    meal_type TEXT NOT NULL CHECK (meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')),
    recipe_id BIGINT REFERENCES recipes(id) ON DELETE SET NULL,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_meal_entries_date ON meal_entries(meal_date DESC);

CREATE TABLE IF NOT EXISTS media_items (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL
        CONSTRAINT chk_media_items_title_length
        CHECK (char_length(btrim(title)) BETWEEN 1 AND 500),
    media_type TEXT NOT NULL CHECK (
        media_type IN (
            'book', 'movie', 'tv_show', 'video_game', 'podcast', 'documentary',
            'anime', 'manga', 'music_album', 'audiobook'
        )
    ),
    status TEXT NOT NULL DEFAULT 'to_watch' CHECK (
        status IN ('to_watch', 'watching', 'completed', 'on_hold', 'dropped', 'plan_to_watch')
    ),
    author_creator TEXT,
    release_year INTEGER,
    genre TEXT,
    progress_current INTEGER NOT NULL DEFAULT 0,
    progress_total INTEGER,
    is_favorite BOOLEAN NOT NULL DEFAULT FALSE,
    rating INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 10),
    notes TEXT,
    review TEXT,
    completion_date TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_media_status ON media_items(status);

-- CREATE TABLE IF NOT EXISTS does not add constraints to an existing legacy
-- table. Add the application-boundary checks without scanning first, then
-- validate them when the historical rows are already clean. A NOT VALID check
-- still protects every subsequent insert and update.
DO $$
DECLARE
    target RECORD;
    constraint_is_valid BOOLEAN;
    has_violations BOOLEAN;
BEGIN
    FOR target IN
        SELECT * FROM (VALUES
            ('tasks', 'chk_tasks_title_length',
                'char_length(btrim(title)) BETWEEN 1 AND 500'),
            ('medications', 'chk_medications_name_length',
                'char_length(btrim(name)) BETWEEN 1 AND 200'),
            ('medication_plans', 'chk_medication_plans_name_length',
                'char_length(btrim(plan_name)) BETWEEN 1 AND 200'),
            ('exercise_catalog', 'chk_exercise_catalog_name_length',
                'char_length(btrim(name)) BETWEEN 1 AND 200'),
            ('exercise_catalog', 'chk_exercise_catalog_muscle_group_length',
                'char_length(btrim(muscle_group)) BETWEEN 1 AND 100'),
            ('training_sets', 'chk_training_sets_name_length',
                'char_length(btrim(name)) BETWEEN 1 AND 200'),
            ('training_set_exercises', 'chk_training_set_exercises_order',
                'order_index >= 0'),
            ('ingredients', 'chk_ingredients_name_length',
                'char_length(btrim(name)) BETWEEN 1 AND 200'),
            ('recipes', 'chk_recipes_name_length',
                'char_length(btrim(name)) BETWEEN 1 AND 300'),
            ('recipe_ingredients', 'chk_recipe_ingredients_unit_length',
                'char_length(btrim(unit)) BETWEEN 1 AND 50'),
            ('inventory', 'chk_inventory_unit_length',
                'char_length(btrim(unit)) BETWEEN 1 AND 50'),
            ('media_items', 'chk_media_items_title_length',
                'char_length(btrim(title)) BETWEEN 1 AND 500')
        ) AS checks(table_name, constraint_name, predicate)
    LOOP
        SELECT convalidated
          INTO constraint_is_valid
          FROM pg_constraint
         WHERE conrelid = to_regclass('public.' || target.table_name)
           AND conname = target.constraint_name;

        IF constraint_is_valid IS NULL THEN
            EXECUTE format(
                'ALTER TABLE %I ADD CONSTRAINT %I CHECK (%s) NOT VALID',
                target.table_name,
                target.constraint_name,
                target.predicate
            );
            constraint_is_valid := FALSE;
        END IF;

        IF NOT constraint_is_valid THEN
            EXECUTE format(
                'SELECT EXISTS (SELECT 1 FROM %I WHERE NOT (%s))',
                target.table_name,
                target.predicate
            ) INTO has_violations;

            IF has_violations THEN
                RAISE WARNING
                    'Constraint % on % remains NOT VALID because historical rows violate it',
                    target.constraint_name,
                    target.table_name;
            ELSE
                EXECUTE format(
                    'ALTER TABLE %I VALIDATE CONSTRAINT %I',
                    target.table_name,
                    target.constraint_name
                );
            END IF;
        END IF;
    END LOOP;
END;
$$;
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_title_check;

-- Preserve the prior bigint index table in-place when upgrading a legacy volume.
DO $$
BEGIN
    IF to_regclass('public.ai_entity_embeddings') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'ai_entity_embeddings'
               AND column_name = 'source_table'
        ) THEN
            ALTER TABLE ai_entity_embeddings RENAME COLUMN source_table TO entity_table;
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'ai_entity_embeddings'
               AND column_name = 'source_id'
        ) THEN
            ALTER TABLE ai_entity_embeddings RENAME COLUMN source_id TO entity_id;
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'ai_entity_embeddings'
               AND column_name = 'entity_text'
        ) THEN
            ALTER TABLE ai_entity_embeddings RENAME COLUMN entity_text TO content;
        END IF;
        IF EXISTS (
            SELECT 1 FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = 'ai_entity_embeddings'
               AND column_name = 'indexed_at'
        ) THEN
            ALTER TABLE ai_entity_embeddings RENAME COLUMN indexed_at TO updated_at;
        END IF;
    END IF;
END;
$$;

CREATE TABLE IF NOT EXISTS ai_entity_embeddings (
    id BIGSERIAL PRIMARY KEY,
    entity_table TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    embedding VECTOR(1024),
    embedding_model TEXT NOT NULL,
    index_version INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    search_document TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple', content)
    ) STORED,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

ALTER TABLE ai_entity_embeddings
    ADD COLUMN IF NOT EXISTS search_document TSVECTOR GENERATED ALWAYS AS (
        to_tsvector('simple', content)
    ) STORED;
ALTER TABLE ai_entity_embeddings
    DROP CONSTRAINT IF EXISTS ai_index_entries_source_table_source_id_key;
DO $$
DECLARE
    old_name TEXT;
    new_name TEXT;
BEGIN
    FOR old_name, new_name IN VALUES
        ('idx_ai_entries_embedding', 'idx_ai_entity_embeddings_vector'),
        ('idx_ai_entries_fts', 'idx_ai_entity_embeddings_content'),
        ('idx_ai_entries_metadata', 'idx_ai_entity_embeddings_metadata'),
        ('idx_ai_entries_version', 'idx_ai_entity_embeddings_version')
    LOOP
        IF to_regclass('public.' || old_name) IS NOT NULL
           AND to_regclass('public.' || new_name) IS NULL THEN
            EXECUTE format('ALTER INDEX %I RENAME TO %I', old_name, new_name);
        ELSIF to_regclass('public.' || old_name) IS NOT NULL THEN
            EXECUTE format('DROP INDEX %I', old_name);
        END IF;
    END LOOP;
END;
$$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_entity_embeddings_identity
    ON ai_entity_embeddings(entity_table, entity_id, embedding_model);
CREATE INDEX IF NOT EXISTS idx_ai_entity_embeddings_version
    ON ai_entity_embeddings(embedding_model, index_version);
CREATE INDEX IF NOT EXISTS idx_ai_entity_embeddings_metadata
    ON ai_entity_embeddings USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_ai_entity_embeddings_content
    ON ai_entity_embeddings USING GIN(search_document);
CREATE INDEX IF NOT EXISTS idx_ai_entity_embeddings_vector
    ON ai_entity_embeddings USING HNSW(embedding vector_cosine_ops);

CREATE TABLE IF NOT EXISTS ai_action_requests (
    request_id UUID PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'pending',
    context JSONB NOT NULL DEFAULT '{}'::jsonb,
    proposed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    decided_at TIMESTAMPTZ,
    CONSTRAINT chk_ai_action_requests_status
        CHECK (status IN ('pending', 'committed', 'rejected')),
    CONSTRAINT chk_ai_action_requests_context_object
        CHECK (jsonb_typeof(context) = 'object'),
    CONSTRAINT chk_ai_action_requests_decision
        CHECK ((status = 'pending' AND decided_at IS NULL)
            OR (status IN ('committed', 'rejected') AND decided_at IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS ai_action_proposals (
    request_id UUID NOT NULL REFERENCES ai_action_requests(request_id) ON DELETE CASCADE,
    action_index INTEGER NOT NULL,
    action TEXT NOT NULL,
    arguments JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (request_id, action_index),
    CONSTRAINT chk_ai_action_proposals_index CHECK (action_index >= 0),
    CONSTRAINT chk_ai_action_proposals_action CHECK (char_length(btrim(action)) BETWEEN 1 AND 100),
    CONSTRAINT chk_ai_action_proposals_arguments_object CHECK (jsonb_typeof(arguments) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_ai_action_requests_pending
    ON ai_action_requests(proposed_at DESC) WHERE status = 'pending';

CREATE TABLE IF NOT EXISTS ai_mutation_audit (
    id BIGSERIAL PRIMARY KEY,
    request_id UUID NOT NULL,
    action_index INTEGER NOT NULL,
    action TEXT NOT NULL,
    entity_table TEXT NOT NULL,
    entity_id TEXT,
    arguments JSONB NOT NULL,
    before_state JSONB,
    after_state JSONB,
    status TEXT NOT NULL CHECK (status IN ('committed', 'rejected', 'failed')),
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_ai_mutation_audit_action_index CHECK (action_index >= 0)
);

ALTER TABLE ai_mutation_audit ADD COLUMN IF NOT EXISTS action_index INTEGER;
WITH ranked AS (
    SELECT id,
           row_number() OVER (PARTITION BY request_id ORDER BY created_at, id) - 1 AS ordinal
      FROM ai_mutation_audit
     WHERE action_index IS NULL
)
UPDATE ai_mutation_audit AS audit
   SET action_index = ranked.ordinal
  FROM ranked
 WHERE audit.id = ranked.id;
ALTER TABLE ai_mutation_audit ALTER COLUMN action_index SET NOT NULL;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
         WHERE conrelid = 'ai_mutation_audit'::regclass
           AND conname = 'chk_ai_mutation_audit_action_index'
    ) THEN
        ALTER TABLE ai_mutation_audit
            ADD CONSTRAINT chk_ai_mutation_audit_action_index
            CHECK (action_index >= 0);
    END IF;
END;
$$;
CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_mutation_audit_request_action
    ON ai_mutation_audit(request_id, action_index);
CREATE INDEX IF NOT EXISTS idx_ai_mutation_audit_created
    ON ai_mutation_audit(created_at DESC);

DO $$
DECLARE
    table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'tasks',
        'medications',
        'medication_plans',
        'medication_plan_times',
        'medication_logs',
        'exercise_catalog',
        'training_sets',
        'training_set_exercises',
        'workout_sessions',
        'workout_session_exercises',
        'ingredients',
        'recipes',
        'recipe_ingredients',
        'inventory',
        'meal_entries',
        'media_items'
    ] LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON %I',
            'trg_' || table_name || '_updated_at',
            table_name
        );
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
            'trg_' || table_name || '_updated_at',
            table_name
        );
    END LOOP;
END;
$$;
