/**
 * Read-only schema metadata derived from database/init.sql and its Alembic
 * entrypoints through 008 AI action approval. Keep this list in
 * step with those files when the database contract changes.
 */

export type Column = {
  name: string
  type: string
  flags?: ('PK' | 'FK' | 'UQ' | 'IDX' | 'NULL')[]
  detail?: string
}

export type Relationship = {
  from: string
  fromColumn: string
  to: string
  toColumn: string
  onDelete: 'CASCADE' | 'SET NULL' | 'RESTRICT'
  nullable: boolean
  meaning: string
}

export type TableDefinition = {
  name: string
  purpose: string
  group: 'Planning' | 'Medication' | 'Training' | 'Kitchen' | 'Media' | 'AI & audit'
  columns: Column[]
  indexes: string[]
  usage: {
    writes: string[]
    reads: string[]
    routes: string[]
    consumers: string[]
    lifecycle?: string
  }
}

const lifecycleColumns: Column[] = [
  { name: 'created_at', type: 'timestamptz' },
  { name: 'updated_at', type: 'timestamptz' },
]

export const tables: TableDefinition[] = [
  {
    name: 'tasks', group: 'Planning', purpose: 'User task records and completion state.',
    columns: [
      { name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'title', type: 'text' },
      { name: 'description', type: 'text', flags: ['NULL'] }, { name: 'priority', type: 'text', flags: ['IDX'] },
      { name: 'completed', type: 'boolean' }, { name: 'due_date', type: 'date', flags: ['IDX', 'NULL'] },
      ...lifecycleColumns, { name: 'completion_date', type: 'timestamptz', flags: ['NULL'] },
    ], indexes: ['idx_tasks_priority (priority)', 'idx_tasks_due_date (due_date) WHERE due_date IS NOT NULL'],
    usage: { writes: ['tasks router', 'AI mutation executor'], reads: ['tasks router', 'AI indexer'], routes: ['/api/tasks/*', '/api/ai/agent/chat'], consumers: ['Tasks page', 'Dashboard'] },
  },
  {
    name: 'medications', group: 'Medication', purpose: 'Unique medication catalog.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'name', type: 'text', flags: ['UQ'] }, { name: 'common_dosage', type: 'text', flags: ['NULL'] }, { name: 'notes', type: 'text', flags: ['NULL'] }, ...lifecycleColumns],
    indexes: ['medications_name_key (name)'],
    usage: { writes: ['medications router', 'AI mutation executor'], reads: ['medications router', 'AI indexer'], routes: ['/api/medications/catalog'], consumers: ['Medicine page'], lifecycle: 'Deleting a medication cascades to its plans and plan records.' },
  },
  {
    name: 'medication_plans', group: 'Medication', purpose: 'Medication dosage plans and active state.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'plan_name', type: 'text' }, { name: 'medication_id', type: 'bigint', flags: ['FK', 'IDX'] }, { name: 'dosage', type: 'text', flags: ['NULL'] }, { name: 'notes', type: 'text', flags: ['NULL'] }, { name: 'active', type: 'boolean' }, ...lifecycleColumns],
    indexes: ['idx_medication_plans_medication (medication_id)'],
    usage: { writes: ['medications router', 'AI mutation executor'], reads: ['medications router', 'AI indexer'], routes: ['/api/medications/plans'], consumers: ['Medicine page'], lifecycle: 'Medication deletion cascades to plans; plan deletion cascades to times and logs.' },
  },
  {
    name: 'medication_plan_times', group: 'Medication', purpose: 'Scheduled administration times for a medication plan.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'plan_id', type: 'bigint', flags: ['FK'] }, { name: 'schedule_time', type: 'time' }, ...lifecycleColumns],
    indexes: ['UNIQUE (plan_id, schedule_time)'],
    usage: { writes: ['medications router', 'AI mutation executor'], reads: ['medications router'], routes: ['/api/medications/plans'], consumers: ['Medicine page'], lifecycle: 'Plan deletion cascades to schedule times.' },
  },
  {
    name: 'medication_logs', group: 'Medication', purpose: 'Recorded medication-plan administrations.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'plan_id', type: 'bigint', flags: ['FK'] }, { name: 'taken_at', type: 'timestamptz', flags: ['IDX'] }, { name: 'scheduled_time', type: 'time', flags: ['NULL'] }, { name: 'notes', type: 'text', flags: ['NULL'] }, ...lifecycleColumns],
    indexes: ['idx_medication_logs_taken_at (taken_at DESC)'],
    usage: { writes: ['medications router', 'AI mutation executor'], reads: ['medications router'], routes: ['/api/medications/logs'], consumers: ['Medicine page'], lifecycle: 'Plan deletion cascades to logs.' },
  },
  {
    name: 'exercise_catalog', group: 'Training', purpose: 'Unique exercise definitions.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'name', type: 'text', flags: ['UQ'] }, { name: 'muscle_group', type: 'text' }, { name: 'equipment', type: 'text', flags: ['NULL'] }, { name: 'description', type: 'text', flags: ['NULL'] }, ...lifecycleColumns],
    indexes: ['exercise_catalog_name_key (name)'],
    usage: { writes: ['gym router', 'AI mutation executor'], reads: ['gym router', 'AI indexer'], routes: ['/api/gym/exercises'], consumers: ['Gym page'], lifecycle: 'Deletion is restricted while referenced by a training template; workout history keeps a name snapshot.' },
  },
  {
    name: 'training_sets', group: 'Training', purpose: 'Reusable workout templates.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'name', type: 'text' }, { name: 'description', type: 'text', flags: ['NULL'] }, ...lifecycleColumns],
    indexes: [],
    usage: { writes: ['gym router', 'AI mutation executor'], reads: ['gym router', 'AI indexer'], routes: ['/api/gym/sets'], consumers: ['Gym page'], lifecycle: 'Template deletion cascades to template exercises and clears historical session linkage.' },
  },
  {
    name: 'training_set_exercises', group: 'Training', purpose: 'Ordered exercise lines within a training-set template.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'training_set_id', type: 'bigint', flags: ['FK', 'IDX'] }, { name: 'exercise_id', type: 'bigint', flags: ['FK'] }, { name: 'order_index', type: 'integer', flags: ['IDX'] }, ...lifecycleColumns],
    indexes: ['UNIQUE (training_set_id, exercise_id)', 'idx_training_set_exercises_set (training_set_id, order_index)'],
    usage: { writes: ['gym router', 'AI mutation executor'], reads: ['gym router', 'AI indexer'], routes: ['/api/gym/sets'], consumers: ['Gym page'], lifecycle: 'Template deletion cascades; referenced exercise deletion is restricted.' },
  },
  {
    name: 'workout_sessions', group: 'Training', purpose: 'Recorded workouts, optionally based on a training-set template.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'training_set_id', type: 'bigint', flags: ['FK', 'NULL'] }, { name: 'set_name', type: 'text', detail: 'Trimmed length 1–200' }, { name: 'session_date', type: 'date', flags: ['IDX'] }, { name: 'duration_minutes', type: 'integer', flags: ['NULL'] }, { name: 'notes', type: 'text', flags: ['NULL'] }, ...lifecycleColumns],
    indexes: ['idx_workout_sessions_date (session_date DESC)'],
    usage: { writes: ['gym router', 'AI mutation executor'], reads: ['gym router', 'AI indexer'], routes: ['/api/gym/history'], consumers: ['Gym page'], lifecycle: 'Template removal clears training_set_id but preserves the session.' },
  },
  {
    name: 'workout_session_exercises', group: 'Training', purpose: 'Exercise performance rows for a recorded workout.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'workout_session_id', type: 'bigint', flags: ['FK', 'IDX'] }, { name: 'exercise_id', type: 'bigint', flags: ['FK', 'NULL'] }, { name: 'exercise_name', type: 'text', detail: 'Trimmed length 1–200' }, { name: 'sets_completed', type: 'integer' }, { name: 'reps_completed', type: 'integer', flags: ['NULL'] }, { name: 'weight_kg', type: 'numeric(8,2)', flags: ['NULL'] }, { name: 'details', type: 'jsonb', detail: 'JSON array' }, ...lifecycleColumns],
    indexes: ['idx_workout_session_exercises_session (workout_session_id)'],
    usage: { writes: ['gym router', 'AI mutation executor'], reads: ['gym router', 'AI indexer'], routes: ['/api/gym/history'], consumers: ['Gym page'], lifecycle: 'Workout deletion cascades. Catalog deletion clears exercise_id but leaves exercise_name history.' },
  },
  {
    name: 'ingredients', group: 'Kitchen', purpose: 'Unique ingredient catalog shared by recipes and inventory.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'name', type: 'text', flags: ['UQ'] }, { name: 'category', type: 'text' }, { name: 'default_unit', type: 'text' }, ...lifecycleColumns],
    indexes: ['ingredients_name_key (name)'],
    usage: { writes: ['kitchen router', 'AI mutation executor'], reads: ['kitchen router', 'AI indexer'], routes: ['/api/recipes/ingredients', '/api/inventory'], consumers: ['Cookbook page', 'Inventory page'], lifecycle: 'Deletion cascades to recipe lines and inventory.' },
  },
  {
    name: 'recipes', group: 'Kitchen', purpose: 'Recipe definitions and preparation details.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'name', type: 'text' }, { name: 'description', type: 'text', flags: ['NULL'] }, { name: 'instructions', type: 'text', flags: ['NULL'] }, { name: 'difficulty', type: 'text', flags: ['NULL'] }, { name: 'prep_time_minutes', type: 'integer', flags: ['NULL'] }, ...lifecycleColumns],
    indexes: [],
    usage: { writes: ['kitchen router', 'AI mutation executor'], reads: ['kitchen router', 'AI indexer'], routes: ['/api/recipes/*', '/api/meal-plans'], consumers: ['Cookbook page', 'Meals page'], lifecycle: 'Deletion cascades recipe lines and clears linked meal entries.' },
  },
  {
    name: 'recipe_ingredients', group: 'Kitchen', purpose: 'Recipe ingredient quantities; a composite-key junction table.',
    columns: [{ name: 'recipe_id', type: 'bigint', flags: ['PK', 'FK'] }, { name: 'ingredient_id', type: 'bigint', flags: ['PK', 'FK'] }, { name: 'quantity', type: 'numeric(10,2)' }, { name: 'unit', type: 'text' }, { name: 'created_at', type: 'timestamptz' }, { name: 'updated_at', type: 'timestamptz' }],
    indexes: ['PRIMARY KEY (recipe_id, ingredient_id)'],
    usage: { writes: ['kitchen router', 'AI mutation executor'], reads: ['kitchen router joins', 'AI indexer joins'], routes: ['/api/recipes/{id}', '/api/recipes/{id}/ingredients'], consumers: ['Cookbook page', 'Meals availability'], lifecycle: 'Deleting either parent cascades to the line.' },
  },
  {
    name: 'inventory', group: 'Kitchen', purpose: 'Current stock for exactly one ingredient.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'ingredient_id', type: 'bigint', flags: ['FK', 'UQ'] }, { name: 'quantity', type: 'numeric(10,2)' }, { name: 'unit', type: 'text' }, { name: 'expiry_date', type: 'date', flags: ['NULL'] }, { name: 'min_quantity', type: 'numeric(10,2)' }, ...lifecycleColumns],
    indexes: ['inventory_ingredient_id_key (ingredient_id)'],
    usage: { writes: ['kitchen router', 'AI mutation executor'], reads: ['kitchen router joins', 'AI indexer'], routes: ['/api/inventory', '/api/recipes/{id}/availability'], consumers: ['Inventory page', 'Cookbook availability'], lifecycle: 'Ingredient deletion cascades to its inventory row.' },
  },
  {
    name: 'meal_entries', group: 'Kitchen', purpose: 'Dated meal-plan entries with an optional recipe.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'meal_date', type: 'date', flags: ['IDX'] }, { name: 'meal_type', type: 'text' }, { name: 'recipe_id', type: 'bigint', flags: ['FK', 'NULL'] }, { name: 'notes', type: 'text', flags: ['NULL'] }, ...lifecycleColumns],
    indexes: ['idx_meal_entries_date (meal_date DESC)'],
    usage: { writes: ['kitchen router', 'AI mutation executor'], reads: ['kitchen router joins', 'AI indexer'], routes: ['/api/meal-plans'], consumers: ['Meals page'], lifecycle: 'Recipe deletion clears recipe_id but preserves the meal entry.' },
  },
  {
    name: 'media_items', group: 'Media', purpose: 'Personal media library, progress, and review state.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'title', type: 'text' }, { name: 'media_type', type: 'text' }, { name: 'status', type: 'text', flags: ['IDX'] }, { name: 'author_creator', type: 'text', flags: ['NULL'] }, { name: 'release_year', type: 'integer', flags: ['NULL'], detail: '1000–9999' }, { name: 'genre', type: 'text', flags: ['NULL'] }, { name: 'progress_current', type: 'integer', detail: 'Non-negative and no greater than total' }, { name: 'progress_total', type: 'integer', flags: ['NULL'], detail: 'Non-negative' }, { name: 'is_favorite', type: 'boolean' }, { name: 'rating', type: 'integer', flags: ['NULL'] }, { name: 'notes', type: 'text', flags: ['NULL'] }, { name: 'review', type: 'text', flags: ['NULL'] }, { name: 'completion_date', type: 'timestamptz', flags: ['NULL'], detail: 'Stamped on transition into completed' }, ...lifecycleColumns],
    indexes: ['idx_media_status (status)'],
    usage: { writes: ['media router', 'AI mutation executor'], reads: ['media router', 'AI indexer'], routes: ['/api/media/*'], consumers: ['Media page'], lifecycle: 'Standalone record; status is a constrained viewing/reading state machine.' },
  },
  {
    name: 'ai_entity_embeddings', group: 'AI & audit', purpose: 'Read-derived, model-versioned search projections for hybrid retrieval.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'entity_table', type: 'text' }, { name: 'entity_id', type: 'text' }, { name: 'content', type: 'text' }, { name: 'metadata', type: 'jsonb', flags: ['IDX'] }, { name: 'embedding', type: 'vector(1024)', flags: ['IDX', 'NULL'] }, { name: 'embedding_model', type: 'text', flags: ['IDX'] }, { name: 'index_version', type: 'integer', flags: ['IDX'] }, { name: 'content_hash', type: 'text' }, { name: 'search_document', type: 'tsvector', flags: ['IDX'] }, { name: 'updated_at', type: 'timestamptz' }],
    indexes: ['uq_ai_entity_embeddings_identity (entity_table, entity_id, embedding_model)', 'idx_ai_entity_embeddings_version (embedding_model, index_version)', 'GIN metadata', 'GIN search_document', 'HNSW embedding vector_cosine_ops'],
    usage: { writes: ['AI indexer reindex/sync loop only'], reads: ['AI hybrid retrieval'], routes: ['/api/ai/agent/chat (through AI service)'], consumers: ['Assistant retrieval'], lifecycle: 'Derived table: source rows are reindexed, changed rows upserted, and stale projections deleted.' },
  },
  {
    name: 'ai_action_requests', group: 'AI & audit', purpose: 'Durable human-review state for every AI write proposal.',
    columns: [{ name: 'request_id', type: 'uuid', flags: ['PK'] }, { name: 'status', type: 'text', flags: ['IDX'], detail: 'pending | committed | rejected' }, { name: 'context', type: 'jsonb' }, { name: 'proposed_at', type: 'timestamptz', flags: ['IDX'] }, { name: 'decided_at', type: 'timestamptz', flags: ['NULL'] }],
    indexes: ['idx_ai_action_requests_pending (proposed_at DESC) WHERE status = pending'],
    usage: { writes: ['API proposal and decision endpoints'], reads: ['API proposal review and approval'], routes: ['/api/internal/ai/proposals', '/api/ai/proposals/{request_id}', '/api/ai/proposals/{request_id}/approve', '/api/ai/proposals/{request_id}/reject'], consumers: ['Assistant proposal card'], lifecycle: 'Created pending before any domain mutation; approval commits with domain and audit writes, while rejection never mutates domain rows.' },
  },
  {
    name: 'ai_action_proposals', group: 'AI & audit', purpose: 'Ordered, typed action payloads awaiting a human decision.',
    columns: [{ name: 'request_id', type: 'uuid', flags: ['PK', 'FK'] }, { name: 'action_index', type: 'integer', flags: ['PK'] }, { name: 'action', type: 'text' }, { name: 'arguments', type: 'jsonb' }],
    indexes: ['PRIMARY KEY (request_id, action_index)'],
    usage: { writes: ['API internal proposal ingestion'], reads: ['API proposal review and approval'], routes: ['/api/internal/ai/proposals', '/api/ai/proposals/{request_id}'], consumers: ['Assistant proposal card', 'Approval executor'], lifecycle: 'Immutable ordered children; request deletion cascades to the proposal rows.' },
  },
  {
    name: 'ai_mutation_audit', group: 'AI & audit', purpose: 'Ordered, transactional audit trail for AI action batches.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'request_id', type: 'uuid' }, { name: 'action_index', type: 'integer' }, { name: 'action', type: 'text' }, { name: 'entity_table', type: 'text' }, { name: 'entity_id', type: 'text', flags: ['NULL'] }, { name: 'arguments', type: 'jsonb' }, { name: 'before_state', type: 'jsonb', flags: ['NULL'] }, { name: 'after_state', type: 'jsonb', flags: ['NULL'] }, { name: 'status', type: 'text' }, { name: 'error', type: 'text', flags: ['NULL'] }, { name: 'created_at', type: 'timestamptz', flags: ['IDX'] }],
    indexes: ['uq_ai_mutation_audit_request_action (request_id, action_index)', 'idx_ai_mutation_audit_created (created_at DESC)'],
    usage: { writes: ['API approved-action transaction'], reads: ['Recent activity and audit tests'], routes: ['/api/ai/proposals/{request_id}/approve', '/api/activity'], consumers: ['Recent activity'], lifecycle: 'Audit insertion and request commit are part of the same transaction as every approved AI mutation.' },
  },
  {
    name: 'activity_events', group: 'AI & audit', purpose: 'Transactional manual-change and backup-restore history.',
    columns: [{ name: 'id', type: 'bigserial', flags: ['PK'] }, { name: 'created_at', type: 'timestamptz', flags: ['IDX'] }, { name: 'source', type: 'text' }, { name: 'action', type: 'text' }, { name: 'entity_table', type: 'text' }, { name: 'entity_id', type: 'text', flags: ['NULL'] }, { name: 'label', type: 'text', flags: ['NULL'] }],
    indexes: ['activity_events_time (created_at DESC)'],
    usage: { writes: ['Domain change triggers and backup restore'], reads: ['Recent activity'], routes: ['/api/activity'], consumers: ['Recent activity'], lifecycle: 'Commits with domain changes; the browser shows seven days. Retained across module restores.' },
  },
]

export const relationships: Relationship[] = [
  { from: 'medication_plans', fromColumn: 'medication_id', to: 'medications', toColumn: 'id', onDelete: 'CASCADE', nullable: false, meaning: 'A plan belongs to one medication.' },
  { from: 'medication_plan_times', fromColumn: 'plan_id', to: 'medication_plans', toColumn: 'id', onDelete: 'CASCADE', nullable: false, meaning: 'A schedule time belongs to one plan.' },
  { from: 'medication_logs', fromColumn: 'plan_id', to: 'medication_plans', toColumn: 'id', onDelete: 'CASCADE', nullable: false, meaning: 'A log records one plan administration.' },
  { from: 'training_set_exercises', fromColumn: 'training_set_id', to: 'training_sets', toColumn: 'id', onDelete: 'CASCADE', nullable: false, meaning: 'A template exercise belongs to a training set.' },
  { from: 'training_set_exercises', fromColumn: 'exercise_id', to: 'exercise_catalog', toColumn: 'id', onDelete: 'RESTRICT', nullable: false, meaning: 'A template exercise selects a catalog exercise.' },
  { from: 'workout_sessions', fromColumn: 'training_set_id', to: 'training_sets', toColumn: 'id', onDelete: 'SET NULL', nullable: true, meaning: 'A workout can retain an optional source template.' },
  { from: 'workout_session_exercises', fromColumn: 'workout_session_id', to: 'workout_sessions', toColumn: 'id', onDelete: 'CASCADE', nullable: false, meaning: 'A performance row belongs to a workout.' },
  { from: 'workout_session_exercises', fromColumn: 'exercise_id', to: 'exercise_catalog', toColumn: 'id', onDelete: 'SET NULL', nullable: true, meaning: 'History keeps exercise_name if its catalog attachment is removed.' },
  { from: 'recipe_ingredients', fromColumn: 'recipe_id', to: 'recipes', toColumn: 'id', onDelete: 'CASCADE', nullable: false, meaning: 'A recipe line belongs to a recipe.' },
  { from: 'recipe_ingredients', fromColumn: 'ingredient_id', to: 'ingredients', toColumn: 'id', onDelete: 'CASCADE', nullable: false, meaning: 'A recipe line selects an ingredient.' },
  { from: 'inventory', fromColumn: 'ingredient_id', to: 'ingredients', toColumn: 'id', onDelete: 'CASCADE', nullable: false, meaning: 'Inventory is a single stock record per ingredient.' },
  { from: 'meal_entries', fromColumn: 'recipe_id', to: 'recipes', toColumn: 'id', onDelete: 'SET NULL', nullable: true, meaning: 'A meal entry may retain its notes without a recipe.' },
  { from: 'ai_action_proposals', fromColumn: 'request_id', to: 'ai_action_requests', toColumn: 'request_id', onDelete: 'CASCADE', nullable: false, meaning: 'Ordered proposals belong to one durable review request.' },
]

export const schemaFeatures = {
  extension: 'vector (pgvector)',
  vectorIndex: 'HNSW cosine index on ai_entity_embeddings.embedding',
  triggers: [
    'set_updated_at: refreshes updated_at before updates',
  ],
  backups: 'Module JSON snapshots use /api/backups/export/{module}; restore checks the file first, then replaces only that module in one transaction. AI audit history is included; search embeddings are rebuilt from the restored records.',
  migrations: [
    '001 initial schema loads database/init.sql',
    '002 removes legacy date_activities and date_retrospectives',
    '003 removes legacy habits, habit_logs, and sleep_logs',
    '004 re-runs the current idempotent schema for bigint deployments',
    '005 removes retired focus/timebox session tables',
    '006 removes offline-sync tables, cursors, and routes',
    '007 aligns PostgreSQL domain constraints with API validation',
  ],
}
