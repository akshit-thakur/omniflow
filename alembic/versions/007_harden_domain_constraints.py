"""harden domain constraints

Revision ID: 007_harden_domain_constraints
Revises: 006_remove_offline_sync
Create Date: 2026-08-25
"""

from alembic import op

revision = "007_harden_domain_constraints"
down_revision = "006_remove_offline_sync"
branch_labels = None
depends_on = None


CHECKS = (
    ("workout_sessions", "chk_workout_sessions_set_name", "char_length(btrim(set_name)) BETWEEN 1 AND 200"),
    ("workout_session_exercises", "chk_workout_session_exercises_name", "char_length(btrim(exercise_name)) BETWEEN 1 AND 200"),
    ("workout_session_exercises", "chk_workout_session_exercises_details_array", "jsonb_typeof(details) = 'array'"),
    ("media_items", "chk_media_items_release_year", "release_year IS NULL OR release_year BETWEEN 1000 AND 9999"),
    ("media_items", "chk_media_items_progress_current", "progress_current >= 0"),
    ("media_items", "chk_media_items_progress_total", "progress_total IS NULL OR progress_total >= 0"),
    ("media_items", "chk_media_items_progress_order", "progress_total IS NULL OR progress_current <= progress_total"),
    ("medication_plans", "chk_medication_plans_medication_id_positive", "medication_id > 0"),
    ("medication_plan_times", "chk_medication_plan_times_plan_id_positive", "plan_id > 0"),
    ("medication_logs", "chk_medication_logs_plan_id_positive", "plan_id > 0"),
    ("training_set_exercises", "chk_training_set_exercises_set_id_positive", "training_set_id > 0"),
    ("training_set_exercises", "chk_training_set_exercises_exercise_id_positive", "exercise_id > 0"),
    ("workout_sessions", "chk_workout_sessions_training_set_id_positive", "training_set_id IS NULL OR training_set_id > 0"),
    ("workout_session_exercises", "chk_workout_session_exercises_session_id_positive", "workout_session_id > 0"),
    ("workout_session_exercises", "chk_workout_session_exercises_exercise_id_positive", "exercise_id IS NULL OR exercise_id > 0"),
    ("recipe_ingredients", "chk_recipe_ingredients_recipe_id_positive", "recipe_id > 0"),
    ("recipe_ingredients", "chk_recipe_ingredients_ingredient_id_positive", "ingredient_id > 0"),
    ("inventory", "chk_inventory_ingredient_id_positive", "ingredient_id > 0"),
    ("meal_entries", "chk_meal_entries_recipe_id_positive", "recipe_id IS NULL OR recipe_id > 0"),
)

ID_TABLES = (
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
    "inventory",
    "meal_entries",
    "media_items",
    "ai_entity_embeddings",
    "ai_mutation_audit",
)


def upgrade() -> None:
    checks = list(CHECKS) + [
        (table_name, f"chk_{table_name}_id_positive", "id > 0")
        for table_name in ID_TABLES
    ]
    for table_name, constraint_name, predicate in checks:
        op.execute(
            f'ALTER TABLE "{table_name}" ADD CONSTRAINT "{constraint_name}" '
            f"CHECK ({predicate}) NOT VALID"
        )
        op.execute(
            f'ALTER TABLE "{table_name}" VALIDATE CONSTRAINT "{constraint_name}"'
        )


def downgrade() -> None:
    checks = list(CHECKS) + [
        (table_name, f"chk_{table_name}_id_positive", "id > 0")
        for table_name in ID_TABLES
    ]
    for table_name, constraint_name, _ in reversed(checks):
        op.execute(
            f'ALTER TABLE "{table_name}" DROP CONSTRAINT IF EXISTS "{constraint_name}"'
        )
