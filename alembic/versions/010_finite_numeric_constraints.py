"""Reject PostgreSQL numeric NaN and enforce finite domain quantities."""

from alembic import op

revision = "010_finite_numeric_constraints"
down_revision = "009_separate_runtime_roles"
branch_labels = None
depends_on = None

CHECKS = (
    ("recipe_ingredients", "chk_recipe_ingredients_quantity_finite", "quantity NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND quantity >= 0"),
    ("inventory", "chk_inventory_quantity_finite", "quantity NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND quantity >= 0"),
    ("inventory", "chk_inventory_min_quantity_finite", "min_quantity NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND min_quantity >= 0"),
    ("workout_session_exercises", "chk_workout_weight_finite", "weight_kg IS NULL OR (weight_kg NOT IN ('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric) AND weight_kg >= 0)"),
)


def upgrade() -> None:
    for table, name, expression in CHECKS:
        op.execute(f'ALTER TABLE "{table}" ADD CONSTRAINT "{name}" CHECK ({expression}) NOT VALID')
        op.execute(f'ALTER TABLE "{table}" VALIDATE CONSTRAINT "{name}"')


def downgrade() -> None:
    for table, name, _ in reversed(CHECKS):
        op.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{name}"')
