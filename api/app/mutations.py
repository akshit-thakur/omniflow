"""Domain mutation executor shared by browser and AI write paths.

This module owns argument normalisation, reference resolution, entity-name
lookups, and the per-action SQL. It deliberately holds no transaction, no
HTTP concern, and no authentication: callers open the transaction and are
responsible for auditing.

Two callers exist:

- `app.routers.ai` after a stored `/api/internal/ai/proposals` request is
  explicitly approved (all-or-nothing batches).
- public API routers for ordinary browser writes.

`app.routers.ai` re-imports these names into its own module namespace and
calls the bare global names, so `unittest.mock.patch.object(ai, ...)`
continues to intercept them. Do not change those call sites to qualified
`mutations.<name>` lookups: the patches would silently stop applying and the
mutation tests would go green without exercising anything.
"""

import json
import re
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException

from .schemas import (
    ExerciseCreate,
    ExerciseUpdate,
    IngredientCreate,
    IngredientUpdate,
    InventoryAdjust,
    InventoryCreate,
    InventoryUpdate,
    MealCreate,
    MealUpdate,
    MediaCreate,
    MediaUpdate,
    MedicationCreate,
    MedicationLogCreate,
    MedicationLogUpdate,
    MedicationPlanCreate,
    MedicationPlanUpdate,
    MedicationUpdate,
    RecipeCreate,
    RecipeIngredientAdd,
    RecipeUpdate,
    TaskCreate,
    TaskUpdate,
    TrainingSetCreate,
    TrainingSetUpdate,
    WorkoutCreate,
    WorkoutUpdate,
)


def _json(value) -> str:
    return json.dumps(value, default=str)


def _today() -> date:
    return datetime.now().astimezone().date()


def _media_completion_for_create(status: str):
    return datetime.now(timezone.utc) if status == "completed" else None


def _apply_media_status_transition(
    changes: dict[str, Any],
    before: dict[str, Any],
) -> None:
    if "status" not in changes:
        return
    if changes["status"] == "completed":
        changes["completion_date"] = (
            before.get("completion_date")
            if before.get("status") == "completed" and before.get("completion_date") is not None
            else datetime.now(timezone.utc)
        )
    else:
        changes["completion_date"] = None


def _validate_media_progress_state(
    changes: dict[str, Any],
    before: dict[str, Any],
) -> None:
    current = changes.get("progress_current", before.get("progress_current"))
    total = changes.get("progress_total", before.get("progress_total"))
    if total is not None and current > total:
        raise HTTPException(422, "progress_current cannot exceed progress_total")


RECIPE_COLS = "id, name, description, instructions, difficulty, prep_time_minutes, created_at"
INVENTORY_SELECT = """
SELECT inv.id, inv.ingredient_id, ing.name, inv.quantity, inv.unit, ing.category, inv.expiry_date,
       inv.min_quantity, inv.quantity <= inv.min_quantity AS is_low_stock,
       (inv.expiry_date IS NOT NULL AND CURRENT_DATE >= inv.created_at::date + CEIL((inv.expiry_date - inv.created_at::date) * 0.9)::int) AS is_expiring_soon
FROM inventory inv JOIN ingredients ing ON ing.id=inv.ingredient_id
"""
MEDIA_COLS = """
id,title,media_type,status,author_creator,release_year,genre,progress_current,
progress_total,is_favorite,rating,notes,review,completion_date,created_at,updated_at
"""

_REFERENCE_PREFIX = "$ref:"
_CONTEXT_REFERENCE = re.compile(r"^\$ref:context\.([a-z][a-z0-9_]*)$")
_ACTION_REFERENCE = re.compile(r"^\$ref:actions\.(\d+)\.(.+)$")

# These identifiers are constants owned by the API, never values supplied by
# the classifier. Keeping the SQL lookup surface closed is part of the mutation
# boundary's security model.
_ENTITY_LOOKUPS: dict[str, tuple[str, str, str]] = {
    "task": ("tasks", "title", "Task"),
    "medication": ("medications", "name", "Medication"),
    "plan": ("medication_plans", "plan_name", "Medication plan"),
    "exercise": ("exercise_catalog", "name", "Exercise"),
    "training_set": ("training_sets", "name", "Training set"),
    "recipe": ("recipes", "name", "Recipe"),
    "ingredient": ("ingredients", "name", "Ingredient"),
    "media": ("media_items", "title", "Media item"),
}

_RESULT_CONTEXT_IDS: dict[str, tuple[str, str]] = {
    "tasks": ("task_id", "id"),
    "medications": ("medication_id", "id"),
    "medication_plans": ("plan_id", "id"),
    "medication_logs": ("medication_log_id", "id"),
    "exercise_catalog": ("exercise_id", "id"),
    "training_sets": ("training_set_id", "id"),
    "workout_sessions": ("workout_id", "id"),
    "recipes": ("recipe_id", "id"),
    "ingredients": ("ingredient_id", "id"),
    "inventory": ("inventory_id", "id"),
    "meal_entries": ("meal_id", "id"),
    "media_items": ("media_id", "id"),
}

_ACTION_ARGUMENT_KEYS: dict[str, frozenset[str]] = {
    "task.create": frozenset({"title", "description", "priority", "due_date"}),
    "task.update": frozenset({"id", "title", "description", "priority", "completed", "due_date"}),
    "task.complete": frozenset({"id"}),
    "task.delete": frozenset({"id"}),
    "medication.create": frozenset({"name", "common_dosage", "notes"}),
    "medication.update": frozenset({"id", "name", "common_dosage", "notes"}),
    "medication.log": frozenset(
        {"plan_id", "medication_id", "taken_at", "scheduled_time", "notes"}
    ),
    "medication.log.update": frozenset(
        {"id", "plan_id", "taken_at", "scheduled_time", "notes"}
    ),
    "medication.log.delete": frozenset({"id"}),
    "medication.delete": frozenset({"id"}),
    "medication.plan.create": frozenset(
        {"plan_name", "medication_id", "dosage", "notes", "schedule_times"}
    ),
    "medication.plan.update": frozenset(
        {"id", "plan_name", "medication_id", "dosage", "notes", "active", "schedule_times"}
    ),
    "medication.plan.delete": frozenset({"id"}),
    "exercise.create": frozenset(
        {
            "name",
            "muscle_group",
            "target_muscle_group",
            "equipment",
            "description",
            "notes",
        }
    ),
    "exercise.update": frozenset(
        {"id", "name", "muscle_group", "target_muscle_group", "equipment", "description", "notes"}
    ),
    "exercise.delete": frozenset({"id"}),
    "training_set.create": frozenset({"name", "description", "exercises"}),
    "training_set.update": frozenset({"id", "name", "description", "exercises"}),
    "training_set.delete": frozenset({"id"}),
    "workout.create": frozenset(
        {
            "training_set_id",
            "name",
            "session_date",
            "duration_minutes",
            "notes",
            "exercises",
        }
    ),
    "workout.update": frozenset(
        {"id", "training_set_id", "name", "session_date", "duration_minutes", "notes", "exercises"}
    ),
    "workout.delete": frozenset({"id"}),
    "recipe.create": frozenset(
        {"name", "description", "instructions", "difficulty", "prep_time_minutes"}
    ),
    "recipe.update": frozenset(
        {"id", "name", "description", "instructions", "difficulty", "prep_time_minutes"}
    ),
    "recipe.delete": frozenset({"id"}),
    "recipe.ingredient.add": frozenset(
        {"recipe_id", "ingredient_id", "quantity", "unit"}
    ),
    "recipe.ingredient.remove": frozenset({"recipe_id", "ingredient_id"}),
    "ingredient.create": frozenset({"name", "category", "default_unit"}),
    "ingredient.update": frozenset({"id", "name", "category", "default_unit"}),
    "ingredient.delete": frozenset({"id"}),
    "inventory.upsert": frozenset(
        {
            "ingredient_id",
            "name",
            "quantity",
            "unit",
            "category",
            "expiry_date",
            "min_quantity",
        }
    ),
    "inventory.adjust": frozenset({"inventory_id", "quantity_delta", "unit"}),
    "inventory.update": frozenset(
        {"id", "name", "quantity", "unit", "category", "expiry_date", "min_quantity"}
    ),
    "inventory.delete": frozenset({"id"}),
    "meal.create": frozenset({"date", "meal_type", "recipe_id", "notes"}),
    "meal.update": frozenset({"id", "date", "meal_type", "recipe_id", "notes"}),
    "meal.delete": frozenset({"id"}),
    "media.create": frozenset(
        {
            "title",
            "media_type",
            "genre",
            "status",
            "author_creator",
            "release_year",
            "progress_current",
            "progress_total",
            "is_favorite",
            "notes",
        }
    ),
    "media.update": frozenset(
        {
            "id",
            "title",
            "media_type",
            "genre",
            "status",
            "author_creator",
            "release_year",
            "progress_current",
            "progress_total",
            "is_favorite",
            "rating",
            "notes",
            "review",
        }
    ),
    "media.progress": frozenset(
        {
            "id",
            "status",
            "progress_current",
            "progress_total",
            "rating",
            "notes",
            "review",
        }
    ),
    "media.delete": frozenset({"id"}),
}

_CANONICAL_ARGUMENT_VALUES: dict[str, dict[str, tuple[str, ...]]] = {
    "task.create": {"priority": ("low", "medium", "high")},
    "task.update": {"priority": ("low", "medium", "high")},
    "recipe.create": {"difficulty": ("Easy", "Medium", "Hard")},
    "recipe.update": {"difficulty": ("Easy", "Medium", "Hard")},
    "meal.create": {"meal_type": ("breakfast", "lunch", "dinner", "snack")},
    "meal.update": {"meal_type": ("breakfast", "lunch", "dinner", "snack")},
    "media.create": {
        "media_type": (
            "book",
            "movie",
            "tv_show",
            "video_game",
            "podcast",
            "documentary",
            "anime",
            "manga",
            "music_album",
            "audiobook",
        ),
        "status": (
            "to_watch",
            "watching",
            "completed",
            "on_hold",
            "dropped",
            "plan_to_watch",
        ),
    },
    "media.update": {
        "media_type": (
            "book",
            "movie",
            "tv_show",
            "video_game",
            "podcast",
            "documentary",
            "anime",
            "manga",
            "music_album",
            "audiobook",
        ),
        "status": (
            "to_watch",
            "watching",
            "completed",
            "on_hold",
            "dropped",
            "plan_to_watch",
        ),
    },
    "media.progress": {
        "status": (
            "to_watch",
            "watching",
            "completed",
            "on_hold",
            "dropped",
            "plan_to_watch",
        ),
    },
}

_TRAINING_SET_EXERCISE_KEYS = frozenset({"exercise_id"})
_WORKOUT_EXERCISE_KEYS = frozenset(
    {"exercise_id", "sets_completed", "reps_completed", "weight_kg", "sets"}
)


def _merge_argument_aliases(
    arguments: dict[str, Any],
    canonical: str,
    aliases: tuple[str, ...],
    label: str,
) -> None:
    supplied = [
        (key, arguments[key])
        for key in (canonical, *aliases)
        if key in arguments and arguments[key] is not None
    ]
    if supplied:
        first = supplied[0][1]
        if any(value != first for _, value in supplied[1:]):
            raise HTTPException(422, f"Conflicting {label} values")
        arguments[canonical] = first
    for alias in aliases:
        arguments.pop(alias, None)


def _argument_registry(action: str) -> frozenset[str]:
    return _ACTION_ARGUMENT_KEYS[action]


def _validate_supported_arguments(action: str, arguments: dict[str, Any]) -> None:
    allowed = _argument_registry(action)
    unsupported = sorted(set(arguments) - allowed)
    if unsupported:
        raise HTTPException(
            422,
            f"Unsupported arguments for {action}: {', '.join(unsupported)}",
        )

    if action not in {"training_set.create", "training_set.update", "workout.create", "workout.update"}:
        return
    nested_allowed = (
        _TRAINING_SET_EXERCISE_KEYS
        if action in {"training_set.create", "training_set.update"}
        else _WORKOUT_EXERCISE_KEYS
    )
    for index, item in enumerate(arguments.get("exercises") or []):
        nested_unsupported = sorted(set(item) - nested_allowed)
        if nested_unsupported:
            raise HTTPException(
                422,
                (
                    f"Unsupported arguments for {action} exercises[{index}]: "
                    f"{', '.join(nested_unsupported)}"
                ),
            )


def _canonicalize_argument_values(action: str, arguments: dict[str, Any]) -> None:
    for key, allowed_values in _CANONICAL_ARGUMENT_VALUES.get(action, {}).items():
        value = arguments.get(key)
        if not isinstance(value, str):
            continue
        normalized = value.strip().replace("-", "_").replace(" ", "_").casefold()
        for allowed in allowed_values:
            if normalized == allowed.casefold():
                arguments[key] = allowed
                break


async def _lock_missing_key(conn, key: str) -> None:
    await conn.execute(
        "SELECT pg_advisory_xact_lock(hashtextextended($1,0))",
        key,
    )


def _clean_name(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(422, f"{label} must be a non-empty string")
    return value.strip()


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise HTTPException(422, f"{label} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise HTTPException(422, f"{label} must be a positive integer") from exc
    if parsed <= 0 or isinstance(value, float) and not value.is_integer():
        raise HTTPException(422, f"{label} must be a positive integer")
    return parsed


def _selected_id(arguments: dict[str, Any], keys: tuple[str, ...], label: str) -> int | None:
    values = [
        _positive_int(arguments[key], label)
        for key in keys
        if key in arguments and arguments[key] is not None
    ]
    if not values:
        return None
    if any(value != values[0] for value in values[1:]):
        raise HTTPException(422, f"Conflicting {label} values")
    return values[0]


def _selected_name(arguments: dict[str, Any], keys: tuple[str, ...], label: str) -> str | None:
    values = [
        _clean_name(arguments[key], label)
        for key in keys
        if key in arguments and arguments[key] is not None
    ]
    if not values:
        return None
    normalized = values[0].casefold()
    if any(value.casefold() != normalized for value in values[1:]):
        raise HTTPException(422, f"Conflicting {label} values")
    return values[0]


async def _resolve_entity_id(
    conn,
    entity: str,
    *,
    entity_id: int | None,
    entity_name: str | None,
    required: bool = True,
    allow_missing_name: bool = False,
) -> int | None:
    table, name_column, label = _ENTITY_LOOKUPS[entity]
    if entity_id is not None:
        row = await conn.fetchrow(
            f"""SELECT id,{name_column} AS entity_name FROM {table}
                WHERE id=$1 FOR KEY SHARE""",
            entity_id,
        )
        if not row:
            raise HTTPException(404, f"{label} not found")
        if (
            entity_name is not None
            and str(row["entity_name"]).strip().casefold() != entity_name.strip().casefold()
        ):
            raise HTTPException(422, f"{label} id and name do not identify the same row")
        return int(row["id"])

    if entity_name is not None:
        rows = await conn.fetch(
            f"""SELECT id,{name_column} AS entity_name FROM {table}
                WHERE lower(btrim({name_column}))=lower(btrim($1))
                ORDER BY id LIMIT 2 FOR KEY SHARE""",
            entity_name,
        )
        if len(rows) > 1:
            raise HTTPException(409, f"{label} name is ambiguous; use an id")
        if rows:
            return int(rows[0]["id"])
        if allow_missing_name:
            return None
        raise HTTPException(404, f"{label} not found")

    if required:
        raise HTTPException(422, f"{label} id or name is required")
    return None


async def _bind_entity(
    conn,
    arguments: dict[str, Any],
    entity: str,
    *,
    id_keys: tuple[str, ...],
    name_keys: tuple[str, ...],
    output_key: str,
    required: bool = True,
) -> int | None:
    label = _ENTITY_LOOKUPS[entity][2]
    entity_id = _selected_id(arguments, id_keys, f"{label} id")
    entity_name = _selected_name(arguments, name_keys, f"{label} name")
    resolved = await _resolve_entity_id(
        conn,
        entity,
        entity_id=entity_id,
        entity_name=entity_name,
        required=required,
    )
    for key in (*id_keys, *name_keys):
        if key != output_key:
            arguments.pop(key, None)
    if resolved is not None:
        arguments[output_key] = resolved
    return resolved


def _bind_plain_id(
    arguments: dict[str, Any],
    *,
    keys: tuple[str, ...],
    output_key: str,
    label: str,
    required: bool = True,
) -> int | None:
    resolved = _selected_id(arguments, keys, label)
    if resolved is None and required:
        raise HTTPException(422, f"{label} is required")
    for key in keys:
        if key != output_key:
            arguments.pop(key, None)
    if resolved is not None:
        arguments[output_key] = resolved
    return resolved


def _resolve_reference(
    value: str,
    context: dict[str, Any],
    prior_results: list[dict[str, Any]],
) -> Any:
    match = _CONTEXT_REFERENCE.fullmatch(value)
    if match:
        key = match.group(1)
        if key not in context:
            raise HTTPException(422, f"Unresolved context reference: {value}")
        return context[key]

    match = _ACTION_REFERENCE.fullmatch(value)
    if not match:
        raise HTTPException(422, f"Invalid action reference: {value}")
    action_index = int(match.group(1))
    if action_index >= len(prior_results):
        raise HTTPException(422, f"Action reference must target a prior action: {value}")

    current: Any = prior_results[action_index]
    for component in match.group(2).split("."):
        if isinstance(current, dict) and component in current:
            current = current[component]
        elif isinstance(current, list) and component.isdigit() and int(component) < len(current):
            current = current[int(component)]
        else:
            raise HTTPException(422, f"Unresolved action reference: {value}")
    return current


def _resolve_references(
    value: Any,
    context: dict[str, Any],
    prior_results: list[dict[str, Any]],
) -> Any:
    if isinstance(value, str) and value.startswith(_REFERENCE_PREFIX):
        return _resolve_reference(value, context, prior_results)
    if isinstance(value, dict):
        return {
            key: _resolve_references(item, context, prior_results)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_resolve_references(item, context, prior_results) for item in value]
    return value


async def _bind_exercise_list(conn, arguments: dict[str, Any]) -> None:
    if "exercises" not in arguments or arguments["exercises"] is None:
        return
    if not isinstance(arguments["exercises"], list):
        raise HTTPException(422, "exercises must be a list")
    resolved_items: list[dict[str, Any]] = []
    for item in arguments["exercises"]:
        if not isinstance(item, dict):
            raise HTTPException(422, "Each exercise must be an object")
        resolved = dict(item)
        await _bind_entity(
            conn,
            resolved,
            "exercise",
            id_keys=("exercise_id",),
            name_keys=("exercise_name", "name"),
            output_key="exercise_id",
        )
        resolved_items.append(resolved)
    arguments["exercises"] = resolved_items


async def _resolve_inventory_id(
    conn,
    arguments: dict[str, Any],
    *,
    output_key: str,
) -> int:
    inventory_id = _selected_id(arguments, ("id", "inventory_id"), "Inventory id")
    ingredient_id = _selected_id(arguments, ("ingredient_id",), "Ingredient id")
    ingredient_name = _selected_name(arguments, ("ingredient_name",), "Ingredient name")

    if inventory_id is not None:
        row = await conn.fetchrow(
            """SELECT inv.id,inv.ingredient_id,ing.name
               FROM inventory inv JOIN ingredients ing ON ing.id=inv.ingredient_id
               WHERE inv.id=$1 FOR UPDATE OF inv""",
            inventory_id,
        )
        if not row:
            raise HTTPException(404, "Inventory item not found")
        if ingredient_id is not None and int(row["ingredient_id"]) != ingredient_id:
            raise HTTPException(422, "Inventory id and ingredient id do not identify the same row")
        if (
            ingredient_name is not None
            and str(row["name"]).strip().casefold() != ingredient_name.casefold()
        ):
            raise HTTPException(422, "Inventory id and ingredient name do not identify the same row")
    else:
        ingredient_id = await _resolve_entity_id(
            conn,
            "ingredient",
            entity_id=ingredient_id,
            entity_name=ingredient_name,
        )
        row = await conn.fetchrow(
            """SELECT inv.id FROM inventory inv
               WHERE inv.ingredient_id=$1 FOR UPDATE OF inv""",
            ingredient_id,
        )
        if not row:
            raise HTTPException(404, "Inventory item not found")
        inventory_id = int(row["id"])

    for key in ("id", "inventory_id", "ingredient_id", "ingredient_name"):
        if key != output_key:
            arguments.pop(key, None)
    arguments[output_key] = inventory_id
    return inventory_id


async def _prepare_action_arguments(
    conn,
    action: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    raw = dict(arguments)
    _canonicalize_argument_values(action, raw)

    if action in {"task.update", "task.complete", "task.delete"}:
        await _bind_entity(
            conn,
            raw,
            "task",
            id_keys=("id", "task_id"),
            name_keys=("task_title",),
            output_key="id",
        )
    elif action in {"medication.log", "medication.log.update"}:
        if action == "medication.log.update":
            _bind_plain_id(
                raw,
                keys=("id", "log_id"),
                output_key="id",
                label="Medication log id",
            )
        plan_selector = any(
            raw.get(key) is not None for key in ("plan_id", "plan_name")
        )
        medication_selector = any(
            raw.get(key) is not None
            for key in ("medication_id", "medication_name")
        )
        medication_id = None
        if medication_selector:
            medication_id = await _bind_entity(
                conn,
                raw,
                "medication",
                id_keys=("medication_id",),
                name_keys=("medication_name",),
                output_key="medication_id",
            )
        if plan_selector:
            plan_id = await _bind_entity(
                conn,
                raw,
                "plan",
                id_keys=("plan_id",),
                name_keys=("plan_name",),
                output_key="plan_id",
            )
            if medication_id is not None:
                belongs = await conn.fetchval(
                    "SELECT medication_id=$2 FROM medication_plans WHERE id=$1",
                    plan_id,
                    medication_id,
                )
                if not belongs:
                    raise HTTPException(422, "Medication plan does not belong to medication")
        elif medication_id is not None:
            plan_id = await conn.fetchval(
                """SELECT id FROM medication_plans
                   WHERE medication_id=$1 AND active=TRUE
                   ORDER BY created_at DESC,id DESC LIMIT 1 FOR KEY SHARE""",
                medication_id,
            )
            if not plan_id:
                raise HTTPException(404, "No active medication plan found")
            raw["plan_id"] = int(plan_id)
        elif action == "medication.log":
            raise HTTPException(422, "Medication plan id/name or medication id/name is required")
        raw.pop("medication_id", None)
    elif action == "medication.log.delete":
        _bind_plain_id(
            raw,
            keys=("id", "log_id"),
            output_key="id",
            label="Medication log id",
        )
    elif action in {"medication.update", "medication.delete"}:
        await _bind_entity(
            conn,
            raw,
            "medication",
            id_keys=("id", "medication_id"),
            name_keys=("medication_name",),
            output_key="id",
        )
    elif action == "medication.plan.create":
        await _bind_entity(
            conn,
            raw,
            "medication",
            id_keys=("medication_id",),
            name_keys=("medication_name",),
            output_key="medication_id",
        )
    elif action in {"medication.plan.update", "medication.plan.delete"}:
        await _bind_entity(
            conn,
            raw,
            "plan",
            id_keys=("id", "plan_id"),
            name_keys=("current_plan_name",) if action == "medication.plan.update" else ("plan_name",),
            output_key="id",
        )
        if action == "medication.plan.update" and any(
            raw.get(key) is not None for key in ("medication_id", "medication_name")
        ):
            await _bind_entity(
                conn,
                raw,
                "medication",
                id_keys=("medication_id",),
                name_keys=("medication_name",),
                output_key="medication_id",
            )
    elif action == "exercise.create":
        _merge_argument_aliases(
            raw,
            "muscle_group",
            ("target_muscle_group",),
            "exercise muscle group",
        )
        _merge_argument_aliases(
            raw,
            "description",
            ("notes",),
            "exercise description",
        )
        raw.setdefault("muscle_group", "Other")
    elif action in {"exercise.update", "exercise.delete"}:
        await _bind_entity(
            conn,
            raw,
            "exercise",
            id_keys=("id", "exercise_id"),
            name_keys=("exercise_name",),
            output_key="id",
        )
        if action == "exercise.update":
            _merge_argument_aliases(
                raw,
                "muscle_group",
                ("target_muscle_group",),
                "exercise muscle group",
            )
            _merge_argument_aliases(
                raw,
                "description",
                ("notes",),
                "exercise description",
            )
    elif action == "training_set.create":
        await _bind_exercise_list(conn, raw)
    elif action in {"training_set.update", "training_set.delete"}:
        await _bind_entity(
            conn,
            raw,
            "training_set",
            id_keys=("id", "training_set_id"),
            name_keys=("training_set_name",),
            output_key="id",
        )
        if action == "training_set.update":
            await _bind_exercise_list(conn, raw)
    elif action == "workout.create":
        await _bind_entity(
            conn,
            raw,
            "training_set",
            id_keys=("training_set_id", "template_id"),
            name_keys=("training_set_name", "template_name"),
            output_key="training_set_id",
            required=False,
        )
        await _bind_exercise_list(conn, raw)
    elif action in {"workout.update", "workout.delete"}:
        _bind_plain_id(
            raw,
            keys=("id", "workout_id"),
            output_key="id",
            label="Workout id",
        )
        if action == "workout.update":
            await _bind_entity(
                conn,
                raw,
                "training_set",
                id_keys=("training_set_id", "template_id"),
                name_keys=("training_set_name", "template_name"),
                output_key="training_set_id",
                required=False,
            )
            await _bind_exercise_list(conn, raw)
    elif action in {"recipe.update", "recipe.delete"}:
        await _bind_entity(
            conn,
            raw,
            "recipe",
            id_keys=("id", "recipe_id"),
            name_keys=("recipe_name",),
            output_key="id",
        )
    elif action in {"recipe.ingredient.add", "recipe.ingredient.remove"}:
        await _bind_entity(
            conn,
            raw,
            "recipe",
            id_keys=("recipe_id",),
            name_keys=("recipe_name",),
            output_key="recipe_id",
        )
        await _bind_entity(
            conn,
            raw,
            "ingredient",
            id_keys=("ingredient_id",),
            name_keys=("ingredient_name",),
            output_key="ingredient_id",
        )
    elif action in {"ingredient.update", "ingredient.delete"}:
        await _bind_entity(
            conn,
            raw,
            "ingredient",
            id_keys=("id", "ingredient_id"),
            name_keys=("ingredient_name",),
            output_key="id",
        )
    elif action == "inventory.upsert":
        ingredient_id = _selected_id(raw, ("ingredient_id",), "Ingredient id")
        supplied_name = _selected_name(
            raw,
            ("name", "ingredient_name"),
            "Ingredient name",
        )
        resolved_ingredient_id = await _resolve_entity_id(
            conn,
            "ingredient",
            entity_id=ingredient_id,
            entity_name=supplied_name,
            required=ingredient_id is not None,
            allow_missing_name=ingredient_id is None,
        )
        raw.pop("ingredient_name", None)
        if resolved_ingredient_id is not None:
            raw["ingredient_id"] = resolved_ingredient_id
            raw.pop("name", None)
        elif supplied_name is not None:
            raw["name"] = supplied_name
    elif action in {"inventory.update", "inventory.delete"}:
        await _resolve_inventory_id(conn, raw, output_key="id")
    elif action == "inventory.adjust":
        await _resolve_inventory_id(conn, raw, output_key="inventory_id")
    elif action == "meal.create":
        await _bind_entity(
            conn,
            raw,
            "recipe",
            id_keys=("recipe_id",),
            name_keys=("recipe_name",),
            output_key="recipe_id",
            required=False,
        )
    elif action in {"meal.update", "meal.delete"}:
        _bind_plain_id(
            raw,
            keys=("id", "meal_id"),
            output_key="id",
            label="Meal id",
        )
        if action == "meal.update" and any(
            key in raw for key in ("recipe_id", "recipe_name")
        ):
            await _bind_entity(
                conn,
                raw,
                "recipe",
                id_keys=("recipe_id",),
                name_keys=("recipe_name",),
                output_key="recipe_id",
                required=False,
            )
    elif action in {"media.update", "media.progress", "media.delete"}:
        await _bind_entity(
            conn,
            raw,
            "media",
            id_keys=("id", "media_id", "media_item_id"),
            name_keys=("media_title",),
            output_key="id",
        )
    if action == "media.progress":
        _merge_argument_aliases(
            raw,
            "rating",
            ("rating_given",),
            "media rating",
        )
        _merge_argument_aliases(
            raw,
            "review",
            ("review_snapshot",),
            "media review",
        )

    _validate_supported_arguments(action, raw)
    return raw


def _update_execution_context(
    context: dict[str, Any],
    entity_table: str,
    entity_id: str,
    result: dict[str, Any] | None,
) -> None:
    if entity_table in _RESULT_CONTEXT_IDS:
        context_key, result_key = _RESULT_CONTEXT_IDS[entity_table]
        value = result.get(result_key) if result else entity_id
        try:
            context[context_key] = _positive_int(value, context_key)
        except HTTPException:
            pass

    if not result:
        return
    for key in (
        "task_id",
        "medication_id",
        "plan_id",
        "exercise_id",
        "training_set_id",
        "recipe_id",
        "ingredient_id",
    ):
        if result.get(key) is not None:
            context[key] = result[key]


async def _execute_action(conn, action: str, arguments: dict):
    if action == "task.create":
        body = TaskCreate.model_validate(arguments)
        row = await conn.fetchrow(
            """INSERT INTO tasks(title,description,priority,due_date) VALUES($1,$2,$3,$4)
               RETURNING *""",
            body.title, body.description, body.priority, body.due_date,
        )
        return "tasks", str(row["id"]), None, dict(row)

    if action in {"task.update", "task.complete"}:
        task_id = int(arguments.get("id", 0))
        before = await conn.fetchrow("SELECT * FROM tasks WHERE id=$1 FOR UPDATE", task_id)
        if not before:
            raise HTTPException(404, "Task not found")
        if action == "task.complete":
            changes = {"completed": True}
        else:
            changes = TaskUpdate.model_validate(
                {key: value for key, value in arguments.items() if key != "id"}
            ).model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, "No task changes supplied")
        if "completed" in changes:
            changes["completion_date"] = (
                __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                if changes["completed"] else None
            )
        values = list(changes.values()) + [task_id]
        assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
        after = await conn.fetchrow(
            f"UPDATE tasks SET {','.join(assignments)} WHERE id=${len(values)} RETURNING *",
            *values,
        )
        return "tasks", str(task_id), dict(before), dict(after)

    if action == "task.delete":
        task_id = int(arguments.get("id", 0))
        before = await conn.fetchrow("SELECT * FROM tasks WHERE id=$1 FOR UPDATE", task_id)
        if not before:
            raise HTTPException(404, "Task not found")
        await conn.execute("DELETE FROM tasks WHERE id=$1", task_id)
        return "tasks", str(task_id), dict(before), None

    if action == "medication.create":
        body = MedicationCreate.model_validate(arguments)
        row = await conn.fetchrow(
            """INSERT INTO medications(name,common_dosage,notes)
               VALUES($1,$2,$3) RETURNING id,name,common_dosage,notes,created_at""",
            body.name, body.common_dosage, body.notes,
        )
        return "medications", str(row["id"]), None, dict(row)

    if action == "medication.update":
        medication_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            "SELECT * FROM medications WHERE id=$1 FOR UPDATE",
            medication_id,
        )
        if not before:
            raise HTTPException(404, "Medication not found")
        changes = MedicationUpdate.model_validate(
            {key: value for key, value in arguments.items() if key != "id"}
        ).model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, "No medication changes supplied")
        values = list(changes.values()) + [medication_id]
        assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
        after = await conn.fetchrow(
            f"UPDATE medications SET {','.join(assignments)} WHERE id=${len(values)} RETURNING *",
            *values,
        )
        return "medications", str(medication_id), dict(before), dict(after)

    if action == "medication.log":
        raw = dict(arguments)
        if raw.get("plan_id") is None and raw.get("medication_id") is not None:
            raw["plan_id"] = await conn.fetchval(
                """SELECT id FROM medication_plans
                   WHERE medication_id=$1 AND active=TRUE
                   ORDER BY created_at DESC,id DESC LIMIT 1""",
                int(raw["medication_id"]),
            )
        raw.pop("medication_id", None)
        body = MedicationLogCreate.model_validate(raw)
        row = await conn.fetchrow(
            """WITH inserted AS (
                 INSERT INTO medication_logs(plan_id,taken_at,scheduled_time,notes)
                 VALUES($1,COALESCE($2,CURRENT_TIMESTAMP),$3,$4)
                 RETURNING *
               )
               SELECT i.id,i.plan_id,mp.plan_name,m.name AS medication_name,mp.dosage,
                      i.taken_at,to_char(i.scheduled_time,'HH24:MI') AS scheduled_time,
                      i.notes,i.created_at
               FROM inserted i JOIN medication_plans mp ON mp.id=i.plan_id
               JOIN medications m ON m.id=mp.medication_id""",
            body.plan_id, body.taken_at, body.scheduled_time, body.notes,
        )
        return "medication_logs", str(row["id"]), None, dict(row)

    if action == "medication.log.update":
        log_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            "SELECT * FROM medication_logs WHERE id=$1 FOR UPDATE",
            log_id,
        )
        if not before:
            raise HTTPException(404, "Medication log not found")
        changes = MedicationLogUpdate.model_validate(
            {key: value for key, value in arguments.items() if key != "id"}
        ).model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, "No medication log changes supplied")
        values = list(changes.values()) + [log_id]
        assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
        after = await conn.fetchrow(
            f"UPDATE medication_logs SET {','.join(assignments)} WHERE id=${len(values)} RETURNING *",
            *values,
        )
        return "medication_logs", str(log_id), dict(before), dict(after)

    if action == "medication.log.delete":
        log_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            "SELECT * FROM medication_logs WHERE id=$1 FOR UPDATE",
            log_id,
        )
        if not before:
            raise HTTPException(404, "Medication log not found")
        await conn.execute("DELETE FROM medication_logs WHERE id=$1", log_id)
        return "medication_logs", str(log_id), dict(before), None

    if action == "medication.delete":
        medication_id = int(arguments.get("id", 0))
        before = await conn.fetchrow("SELECT * FROM medications WHERE id=$1 FOR UPDATE", medication_id)
        if not before:
            raise HTTPException(404, "Medication not found")
        await conn.execute("DELETE FROM medications WHERE id=$1", medication_id)
        return "medications", str(medication_id), dict(before), None

    if action == "medication.plan.create":
        body = MedicationPlanCreate.model_validate(arguments)
        plan_id = await conn.fetchval(
            """INSERT INTO medication_plans(plan_name,medication_id,dosage,notes)
               VALUES($1,$2,$3,$4) RETURNING id""",
            body.plan_name, body.medication_id, body.dosage, body.notes,
        )
        if body.schedule_times:
            await conn.executemany(
                "INSERT INTO medication_plan_times(plan_id,schedule_time) VALUES($1,$2)",
                [(plan_id, value) for value in body.schedule_times],
            )
        row = await conn.fetchrow(
            """SELECT mp.id,mp.plan_name,mp.medication_id,m.name AS medication_name,
                      mp.dosage,mp.notes,mp.active,mp.created_at
               FROM medication_plans mp JOIN medications m ON m.id=mp.medication_id
               WHERE mp.id=$1""",
            plan_id,
        )
        return "medication_plans", str(plan_id), None, dict(row)

    if action == "medication.plan.update":
        plan_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            "SELECT * FROM medication_plans WHERE id=$1 FOR UPDATE",
            plan_id,
        )
        if not before:
            raise HTTPException(404, "Medication plan not found")
        body = MedicationPlanUpdate.model_validate(
            {key: value for key, value in arguments.items() if key != "id"}
        )
        changes = body.model_dump(exclude_unset=True)
        schedule_times = changes.pop("schedule_times", None)
        if not changes and schedule_times is None:
            raise HTTPException(422, "No medication plan changes supplied")
        if changes:
            values = list(changes.values()) + [plan_id]
            assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
            await conn.execute(
                f"UPDATE medication_plans SET {','.join(assignments)} WHERE id=${len(values)}",
                *values,
            )
        if schedule_times is not None:
            await conn.execute("DELETE FROM medication_plan_times WHERE plan_id=$1", plan_id)
            if schedule_times:
                await conn.executemany(
                    "INSERT INTO medication_plan_times(plan_id,schedule_time) VALUES($1,$2)",
                    [(plan_id, value) for value in schedule_times],
                )
        after = await conn.fetchrow("SELECT * FROM medication_plans WHERE id=$1", plan_id)
        return "medication_plans", str(plan_id), dict(before), dict(after)

    if action == "medication.plan.delete":
        plan_id = int(arguments.get("id", 0))
        before = await conn.fetchrow("SELECT * FROM medication_plans WHERE id=$1 FOR UPDATE", plan_id)
        if not before:
            raise HTTPException(404, "Medication plan not found")
        await conn.execute("DELETE FROM medication_plans WHERE id=$1", plan_id)
        return "medication_plans", str(plan_id), dict(before), None

    if action == "exercise.create":
        raw = dict(arguments)
        _merge_argument_aliases(
            raw,
            "muscle_group",
            ("target_muscle_group",),
            "exercise muscle group",
        )
        _merge_argument_aliases(
            raw,
            "description",
            ("notes",),
            "exercise description",
        )
        raw.setdefault("muscle_group", "Other")
        body = ExerciseCreate.model_validate(raw)
        row = await conn.fetchrow(
            """INSERT INTO exercise_catalog(name,muscle_group,equipment,description)
               VALUES($1,$2,$3,$4) RETURNING id,name,muscle_group,equipment,description""",
            body.name, body.muscle_group, body.equipment, body.description,
        )
        return "exercise_catalog", str(row["id"]), None, dict(row)

    if action == "exercise.update":
        exercise_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            "SELECT * FROM exercise_catalog WHERE id=$1 FOR UPDATE",
            exercise_id,
        )
        if not before:
            raise HTTPException(404, "Exercise not found")
        changes = ExerciseUpdate.model_validate(
            {key: value for key, value in arguments.items() if key != "id"}
        ).model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, "No exercise changes supplied")
        values = list(changes.values()) + [exercise_id]
        assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
        after = await conn.fetchrow(
            f"UPDATE exercise_catalog SET {','.join(assignments)} WHERE id=${len(values)} RETURNING *",
            *values,
        )
        return "exercise_catalog", str(exercise_id), dict(before), dict(after)

    if action == "exercise.delete":
        exercise_id = int(arguments.get("id", 0))
        before = await conn.fetchrow("SELECT * FROM exercise_catalog WHERE id=$1 FOR UPDATE", exercise_id)
        if not before:
            raise HTTPException(404, "Exercise not found")
        await conn.execute("DELETE FROM exercise_catalog WHERE id=$1", exercise_id)
        return "exercise_catalog", str(exercise_id), dict(before), None

    if action == "training_set.create":
        body = TrainingSetCreate.model_validate(arguments)
        set_id = await conn.fetchval(
            "INSERT INTO training_sets(name,description) VALUES($1,$2) RETURNING id",
            body.name, body.description,
        )
        if body.exercises:
            await conn.executemany(
                """INSERT INTO training_set_exercises(training_set_id,exercise_id,order_index)
                   VALUES($1,$2,$3)""",
                [(set_id, item.exercise_id, index) for index, item in enumerate(body.exercises)],
            )
        row = await conn.fetchrow("SELECT id,name,description,created_at FROM training_sets WHERE id=$1", set_id)
        return "training_sets", str(set_id), None, dict(row)

    if action == "training_set.update":
        set_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            "SELECT * FROM training_sets WHERE id=$1 FOR UPDATE",
            set_id,
        )
        if not before:
            raise HTTPException(404, "Training set not found")
        body = TrainingSetUpdate.model_validate(
            {key: value for key, value in arguments.items() if key != "id"}
        )
        changes = body.model_dump(exclude_unset=True)
        exercises = changes.pop("exercises", None)
        if not changes and exercises is None:
            raise HTTPException(422, "No training set changes supplied")
        if changes:
            values = list(changes.values()) + [set_id]
            assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
            await conn.execute(
                f"UPDATE training_sets SET {','.join(assignments)} WHERE id=${len(values)}",
                *values,
            )
        if exercises is not None:
            await conn.execute(
                "DELETE FROM training_set_exercises WHERE training_set_id=$1",
                set_id,
            )
            if exercises:
                await conn.executemany(
                    """INSERT INTO training_set_exercises(training_set_id,exercise_id,order_index)
                       VALUES($1,$2,$3)""",
                    [(set_id, item["exercise_id"], index) for index, item in enumerate(exercises)],
                )
        after = await conn.fetchrow("SELECT * FROM training_sets WHERE id=$1", set_id)
        return "training_sets", str(set_id), dict(before), dict(after)

    if action == "training_set.delete":
        set_id = int(arguments.get("id", 0))
        before = await conn.fetchrow("SELECT * FROM training_sets WHERE id=$1 FOR UPDATE", set_id)
        if not before:
            raise HTTPException(404, "Training set not found")
        await conn.execute("DELETE FROM training_sets WHERE id=$1", set_id)
        return "training_sets", str(set_id), dict(before), None

    if action == "workout.create":
        raw = dict(arguments)
        raw["training_set_id"] = raw.get("training_set_id") or raw.get("template_id")
        raw["session_date"] = raw.get("session_date") or _today()
        body = WorkoutCreate.model_validate(raw)
        set_name = body.name
        if body.training_set_id and not set_name:
            set_name = await conn.fetchval("SELECT name FROM training_sets WHERE id=$1", body.training_set_id)
        set_name = set_name or f"Workout {body.session_date.isoformat()}"
        workout_id = await conn.fetchval(
            """INSERT INTO workout_sessions(training_set_id,set_name,session_date,duration_minutes,notes)
               VALUES($1,$2,$3,$4,$5) RETURNING id""",
            body.training_set_id, set_name, body.session_date, body.duration_minutes, body.notes,
        )
        for item in body.exercises:
            exercise_name = item.exercise_name
            if item.exercise_id:
                exercise_name = await conn.fetchval("SELECT name FROM exercise_catalog WHERE id=$1", item.exercise_id)
            if not exercise_name:
                raise HTTPException(422, "Each workout exercise needs a valid exercise")
            await conn.execute(
                """INSERT INTO workout_session_exercises(
                     workout_session_id,exercise_id,exercise_name,sets_completed,
                     reps_completed,weight_kg,details
                   ) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)""",
                workout_id, item.exercise_id, exercise_name,
                (
                    item.sets_completed
                    if "sets_completed" in item.model_fields_set
                    else len(item.sets)
                ),
                item.reps_completed, item.weight_kg,
                _json(item.sets),
            )
        row = await conn.fetchrow("SELECT * FROM workout_sessions WHERE id=$1", workout_id)
        return "workout_sessions", str(workout_id), None, dict(row)

    if action == "workout.update":
        workout_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            "SELECT * FROM workout_sessions WHERE id=$1 FOR UPDATE",
            workout_id,
        )
        if not before:
            raise HTTPException(404, "Workout not found")
        body = WorkoutUpdate.model_validate(
            {key: value for key, value in arguments.items() if key != "id"}
        )
        changes = body.model_dump(exclude_unset=True)
        exercises = changes.pop("exercises", None)
        if "name" in changes:
            changes["set_name"] = changes.pop("name")
        if not changes and exercises is None:
            raise HTTPException(422, "No workout changes supplied")
        if changes:
            values = list(changes.values()) + [workout_id]
            assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
            await conn.execute(
                f"UPDATE workout_sessions SET {','.join(assignments)} WHERE id=${len(values)}",
                *values,
            )
        if exercises is not None:
            await conn.execute(
                "DELETE FROM workout_session_exercises WHERE workout_session_id=$1",
                workout_id,
            )
            for item in exercises:
                exercise_id = item.get("exercise_id")
                exercise_name = (
                    await conn.fetchval("SELECT name FROM exercise_catalog WHERE id=$1", exercise_id)
                    if exercise_id else item.get("exercise_name")
                )
                if not exercise_name:
                    raise HTTPException(422, "Each workout exercise needs a valid exercise")
                await conn.execute(
                    """INSERT INTO workout_session_exercises(
                         workout_session_id,exercise_id,exercise_name,sets_completed,
                         reps_completed,weight_kg,details
                       ) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)""",
                    workout_id,
                    exercise_id,
                    exercise_name,
                    item.get("sets_completed", len(item.get("sets", []))),
                    item.get("reps_completed"),
                    item.get("weight_kg"),
                    _json(item.get("sets", [])),
                )
        after = await conn.fetchrow("SELECT * FROM workout_sessions WHERE id=$1", workout_id)
        return "workout_sessions", str(workout_id), dict(before), dict(after)

    if action == "workout.delete":
        workout_id = int(arguments.get("id", 0))
        before = await conn.fetchrow("SELECT * FROM workout_sessions WHERE id=$1 FOR UPDATE", workout_id)
        if not before:
            raise HTTPException(404, "Workout history not found")
        await conn.execute("DELETE FROM workout_sessions WHERE id=$1", workout_id)
        return "workout_sessions", str(workout_id), dict(before), None

    if action == "recipe.create":
        body = RecipeCreate.model_validate(arguments)
        row = await conn.fetchrow(
            """INSERT INTO recipes(name,description,instructions,difficulty,prep_time_minutes)
               VALUES($1,$2,$3,$4,$5)
               RETURNING id,name,description,instructions,difficulty,prep_time_minutes,created_at""",
            body.name, body.description, body.instructions, body.difficulty, body.prep_time_minutes,
        )
        return "recipes", str(row["id"]), None, dict(row)

    if action == "recipe.update":
        recipe_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(f"SELECT {RECIPE_COLS} FROM recipes WHERE id=$1 FOR UPDATE", recipe_id)
        if not before:
            raise HTTPException(404, "Recipe not found")
        changes = RecipeUpdate.model_validate(
            {key: value for key, value in arguments.items() if key != "id"}
        ).model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, "No recipe changes supplied")
        values = list(changes.values()) + [recipe_id]
        assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
        after = await conn.fetchrow(
            f"UPDATE recipes SET {','.join(assignments)} WHERE id=${len(values)} RETURNING {RECIPE_COLS}",
            *values,
        )
        return "recipes", str(recipe_id), dict(before), dict(after)

    if action == "recipe.delete":
        recipe_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(f"SELECT {RECIPE_COLS} FROM recipes WHERE id=$1 FOR UPDATE", recipe_id)
        if not before:
            raise HTTPException(404, "Recipe not found")
        await conn.execute("DELETE FROM recipes WHERE id=$1", recipe_id)
        return "recipes", str(recipe_id), dict(before), None

    if action == "recipe.ingredient.add":
        recipe_id = int(arguments.get("recipe_id", 0))
        body = RecipeIngredientAdd.model_validate(
            {key: value for key, value in arguments.items() if key != "recipe_id"}
        )
        await _lock_missing_key(
            conn,
            f"recipe_ingredient:{recipe_id}:{body.ingredient_id}",
        )
        before = await conn.fetchrow(
            """SELECT recipe_id,ingredient_id,quantity,unit FROM recipe_ingredients
               WHERE recipe_id=$1 AND ingredient_id=$2 FOR UPDATE""",
            recipe_id,
            body.ingredient_id,
        )
        row = await conn.fetchrow(
            """INSERT INTO recipe_ingredients(recipe_id,ingredient_id,quantity,unit)
               VALUES($1,$2,$3,$4)
               ON CONFLICT(recipe_id,ingredient_id) DO UPDATE
               SET quantity=EXCLUDED.quantity, unit=EXCLUDED.unit
               RETURNING recipe_id,ingredient_id,quantity,unit""",
            recipe_id, body.ingredient_id, body.quantity, body.unit,
        )
        return (
            "recipe_ingredients",
            f"{recipe_id}:{body.ingredient_id}",
            dict(before) if before else None,
            dict(row),
        )

    if action == "recipe.ingredient.remove":
        recipe_id = int(arguments.get("recipe_id", 0))
        ingredient_id = int(arguments.get("ingredient_id", 0))
        before = await conn.fetchrow(
            """SELECT recipe_id,ingredient_id,quantity,unit FROM recipe_ingredients
               WHERE recipe_id=$1 AND ingredient_id=$2 FOR UPDATE""",
            recipe_id, ingredient_id,
        )
        if not before:
            raise HTTPException(404, "Recipe ingredient not found")
        await conn.execute(
            "DELETE FROM recipe_ingredients WHERE recipe_id=$1 AND ingredient_id=$2",
            recipe_id, ingredient_id,
        )
        return "recipe_ingredients", f"{recipe_id}:{ingredient_id}", dict(before), None

    if action == "ingredient.create":
        body = IngredientCreate.model_validate(arguments)
        row = await conn.fetchrow(
            """INSERT INTO ingredients(name,category,default_unit)
               VALUES($1,$2,$3) RETURNING id,name,category,default_unit""",
            body.name, body.category, body.default_unit,
        )
        return "ingredients", str(row["id"]), None, dict(row)

    if action == "ingredient.update":
        ingredient_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            "SELECT * FROM ingredients WHERE id=$1 FOR UPDATE",
            ingredient_id,
        )
        if not before:
            raise HTTPException(404, "Ingredient not found")
        changes = IngredientUpdate.model_validate(
            {key: value for key, value in arguments.items() if key != "id"}
        ).model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, "No ingredient changes supplied")
        values = list(changes.values()) + [ingredient_id]
        assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
        after = await conn.fetchrow(
            f"UPDATE ingredients SET {','.join(assignments)} WHERE id=${len(values)} RETURNING *",
            *values,
        )
        return "ingredients", str(ingredient_id), dict(before), dict(after)

    if action == "ingredient.delete":
        ingredient_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            "SELECT * FROM ingredients WHERE id=$1 FOR UPDATE",
            ingredient_id,
        )
        if not before:
            raise HTTPException(404, "Ingredient not found")
        await conn.execute("DELETE FROM ingredients WHERE id=$1", ingredient_id)
        return "ingredients", str(ingredient_id), dict(before), None

    if action == "inventory.upsert":
        raw = dict(arguments)
        if raw.get("name") is None and raw.get("ingredient_id") is not None:
            ingredient = await conn.fetchrow(
                "SELECT name,category,default_unit FROM ingredients WHERE id=$1",
                int(raw["ingredient_id"]),
            )
            if not ingredient:
                raise HTTPException(404, "Ingredient not found")
            raw["name"] = ingredient["name"]
            raw["category"] = raw.get("category") or ingredient["category"]
            raw["unit"] = raw.get("unit") or ingredient["default_unit"]
        raw.pop("ingredient_id", None)
        body = InventoryCreate.model_validate(raw)
        await _lock_missing_key(
            conn,
            f"inventory:{body.name.strip().casefold()}",
        )
        matching_ingredients = await conn.fetch(
            """SELECT id,name FROM ingredients
               WHERE lower(btrim(name))=lower(btrim($1))
               ORDER BY id LIMIT 2 FOR UPDATE""",
            body.name,
        )
        if len(matching_ingredients) > 1:
            raise HTTPException(409, "Ingredient name is ambiguous; use an id")
        if matching_ingredients:
            ingredient_id = int(matching_ingredients[0]["id"])
            before = await conn.fetchrow(
                f"{INVENTORY_SELECT} WHERE inv.ingredient_id=$1 FOR UPDATE OF inv,ing",
                ingredient_id,
            )
            await conn.execute(
                "UPDATE ingredients SET category=$2 WHERE id=$1",
                ingredient_id,
                body.category,
            )
        else:
            before = None
            ingredient_id = await conn.fetchval(
                """INSERT INTO ingredients(name,category,default_unit)
                   VALUES($1,$2,$3) RETURNING id""",
                body.name,
                body.category,
                body.unit,
            )
        item_id = await conn.fetchval(
            """INSERT INTO inventory(ingredient_id,quantity,unit,expiry_date,min_quantity)
               VALUES($1,$2,$3,$4,$5)
               ON CONFLICT(ingredient_id) DO UPDATE SET
                 quantity=EXCLUDED.quantity, unit=EXCLUDED.unit,
                 expiry_date=EXCLUDED.expiry_date, min_quantity=EXCLUDED.min_quantity
               RETURNING id""",
            ingredient_id, body.quantity, body.unit, body.expiry_date, body.min_quantity,
        )
        row = await conn.fetchrow(
            """SELECT inv.id,ing.name,inv.quantity,inv.unit,ing.category,inv.expiry_date,
                      inv.min_quantity,inv.quantity <= inv.min_quantity AS is_low_stock
               FROM inventory inv JOIN ingredients ing ON ing.id=inv.ingredient_id
               WHERE inv.id=$1""",
            item_id,
        )
        return "inventory", str(item_id), dict(before) if before else None, dict(row)

    if action == "inventory.adjust":
        body = InventoryAdjust.model_validate(arguments)
        before = await conn.fetchrow(
            f"{INVENTORY_SELECT} WHERE inv.id=$1 FOR UPDATE OF inv,ing",
            body.inventory_id,
        )
        if not before:
            raise HTTPException(404, "Inventory item not found")
        if body.unit is not None and body.unit.strip().casefold() != str(before["unit"]).strip().casefold():
            raise HTTPException(422, "inventory.adjust does not convert between units")
        updated = await conn.fetchval(
            """UPDATE inventory SET quantity=quantity+$2
               WHERE id=$1 AND quantity+$2 >= 0 RETURNING id""",
            body.inventory_id,
            body.quantity_delta,
        )
        if not updated:
            raise HTTPException(422, "Inventory adjustment would make quantity negative")
        after = await conn.fetchrow(
            f"{INVENTORY_SELECT} WHERE inv.id=$1",
            body.inventory_id,
        )
        return "inventory", str(body.inventory_id), dict(before), dict(after)

    if action == "inventory.update":
        item_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            f"{INVENTORY_SELECT} WHERE inv.id=$1 FOR UPDATE OF inv,ing",
            item_id,
        )
        if not before:
            raise HTTPException(404, "Inventory item not found")
        changes = InventoryUpdate.model_validate(
            {key: value for key, value in arguments.items() if key != "id"}
        ).model_dump(exclude_unset=True)
        ingredient_changes = {k: changes.pop(k) for k in ("name", "category") if k in changes}
        ingredient_id = await conn.fetchval("SELECT ingredient_id FROM inventory WHERE id=$1", item_id)
        if ingredient_changes:
            values = list(ingredient_changes.values()) + [ingredient_id]
            assignments = [f"{key}=${index}" for index, key in enumerate(ingredient_changes, 1)]
            await conn.execute(
                f"UPDATE ingredients SET {','.join(assignments)} WHERE id=${len(values)}",
                *values,
            )
        if changes:
            values = list(changes.values()) + [item_id]
            assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
            await conn.execute(
                f"UPDATE inventory SET {','.join(assignments)} WHERE id=${len(values)}",
                *values,
            )
        if not ingredient_changes and not changes:
            raise HTTPException(422, "No inventory changes supplied")
        after = await conn.fetchrow(f"{INVENTORY_SELECT} WHERE inv.id=$1", item_id)
        return "inventory", str(item_id), dict(before), dict(after)

    if action == "inventory.delete":
        item_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            f"{INVENTORY_SELECT} WHERE inv.id=$1 FOR UPDATE OF inv,ing",
            item_id,
        )
        if not before:
            raise HTTPException(404, "Inventory item not found")
        await conn.execute("DELETE FROM inventory WHERE id=$1", item_id)
        return "inventory", str(item_id), dict(before), None

    if action == "meal.create":
        body = MealCreate.model_validate(arguments)
        row = await conn.fetchrow(
            """INSERT INTO meal_entries(meal_date,meal_type,recipe_id,notes)
               VALUES($1,$2,$3,$4) RETURNING id,meal_date AS date,meal_type,recipe_id,notes""",
            body.date, body.meal_type, body.recipe_id, body.notes,
        )
        return "meal_entries", str(row["id"]), None, dict(row)

    if action == "meal.update":
        meal_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(
            "SELECT * FROM meal_entries WHERE id=$1 FOR UPDATE",
            meal_id,
        )
        if not before:
            raise HTTPException(404, "Meal entry not found")
        changes = MealUpdate.model_validate(
            {key: value for key, value in arguments.items() if key != "id"}
        ).model_dump(exclude_unset=True)
        if "date" in changes:
            changes["meal_date"] = changes.pop("date")
        if not changes:
            raise HTTPException(422, "No meal changes supplied")
        values = list(changes.values()) + [meal_id]
        assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
        after = await conn.fetchrow(
            f"UPDATE meal_entries SET {','.join(assignments)} WHERE id=${len(values)} RETURNING *",
            *values,
        )
        return "meal_entries", str(meal_id), dict(before), dict(after)

    if action == "meal.delete":
        meal_id = int(arguments.get("id", 0))
        before = await conn.fetchrow("SELECT * FROM meal_entries WHERE id=$1 FOR UPDATE", meal_id)
        if not before:
            raise HTTPException(404, "Meal entry not found")
        await conn.execute("DELETE FROM meal_entries WHERE id=$1", meal_id)
        return "meal_entries", str(meal_id), dict(before), None
    if action == "media.create":
        body = MediaCreate.model_validate(arguments)
        completion_date = _media_completion_for_create(body.status)
        row = await conn.fetchrow(
            """INSERT INTO media_items(
                 title,media_type,status,author_creator,release_year,genre,
                 progress_current,progress_total,is_favorite,notes,completion_date
               ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING *""",
            body.title, body.media_type, body.status, body.author_creator, body.release_year,
            body.genre, body.progress_current, body.progress_total, body.is_favorite, body.notes,
            completion_date,
        )
        return "media_items", str(row["id"]), None, dict(row)

    if action == "media.progress":
        media_id = int(arguments.get("id") or arguments.get("media_item_id") or 0)
        before = await conn.fetchrow("SELECT * FROM media_items WHERE id=$1 FOR UPDATE", media_id)
        if not before:
            raise HTTPException(404, "Media item not found")
        status_value = arguments.get("status")
        if status_value == "in_progress":
            status_value = "watching"
        if status_value == "backlog":
            status_value = "to_watch"
        updates = {
            "status": status_value,
            "progress_current": arguments.get("progress_current"),
            "progress_total": arguments.get("progress_total"),
            "rating": (
                arguments["rating"]
                if "rating" in arguments
                else arguments.get("rating_given")
            ),
            "notes": arguments.get("notes"),
            "review": (
                arguments["review"]
                if "review" in arguments
                else arguments.get("review_snapshot")
            ),
        }
        updates = {key: value for key, value in updates.items() if value is not None}
        if not updates:
            raise HTTPException(422, "No media progress supplied")
        media_update = MediaUpdate.model_validate(updates).model_dump(exclude_unset=True)
        _validate_media_progress_state(media_update, dict(before))
        _apply_media_status_transition(media_update, dict(before))
        values = list(media_update.values()) + [media_id]
        assignments = [f"{key}=${index}" for index, key in enumerate(media_update, 1)]
        after = await conn.fetchrow(
            f"UPDATE media_items SET {','.join(assignments)} WHERE id=${len(values)} RETURNING *",
            *values,
        )
        return "media_items", str(media_id), dict(before), dict(after)

    if action == "media.update":
        media_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(f"SELECT {MEDIA_COLS} FROM media_items WHERE id=$1 FOR UPDATE", media_id)
        if not before:
            raise HTTPException(404, "Media item not found")
        changes = MediaUpdate.model_validate(
            {key: value for key, value in arguments.items() if key != "id"}
        ).model_dump(exclude_unset=True)
        if not changes:
            raise HTTPException(422, "No media changes supplied")
        _validate_media_progress_state(changes, dict(before))
        _apply_media_status_transition(changes, dict(before))
        values = list(changes.values()) + [media_id]
        assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
        after = await conn.fetchrow(
            f"UPDATE media_items SET {','.join(assignments)} WHERE id=${len(values)} RETURNING {MEDIA_COLS}",
            *values,
        )
        return "media_items", str(media_id), dict(before), dict(after)

    if action == "media.delete":
        media_id = int(arguments.get("id", 0))
        before = await conn.fetchrow(f"SELECT {MEDIA_COLS} FROM media_items WHERE id=$1 FOR UPDATE", media_id)
        if not before:
            raise HTTPException(404, "Media item not found")
        await conn.execute("DELETE FROM media_items WHERE id=$1", media_id)
        return "media_items", str(media_id), dict(before), None

    raise HTTPException(422, "Action is not allowlisted")
