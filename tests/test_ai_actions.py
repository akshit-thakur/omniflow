from contextlib import asynccontextmanager
from decimal import Decimal
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
API_PATH = str(ROOT / "api")
sys.path.insert(0, API_PATH)

from app.schemas import (  # noqa: E402
    AI_WRITE_ACTIONS,
    AIActionRequest,
    ExerciseCreate,
    InventoryAdjust,
    InventoryCreate,
    InventoryUpdate,
    MediaUpdate,
    MedicationCreate,
    RecipeIngredientAdd,
    RecipeUpdate,
    TaskCreate,
    TaskUpdate,
    WorkoutExercise,
)
from pydantic import ValidationError  # noqa: E402


OLD_PARITY_ACTIONS = {
    "task.create": {"title": "Buy milk", "priority": "high"},
    "medication.create": {"name": "Vitamin D", "common_dosage": "1000 IU"},
    "medication.log": {"plan_id": 1},
    "exercise.create": {"name": "Squat", "target_muscle_group": "Legs"},
    "training_set.create": {"name": "Leg Day"},
    "workout.create": {"session_date": "2026-01-15", "name": "Morning workout"},
    "recipe.create": {"name": "Pasta", "instructions": "Boil and serve"},
    "ingredient.create": {"name": "Tomato"},
    "inventory.upsert": {"name": "Tomato", "quantity": 2, "unit": "piece"},
    "media.create": {"title": "Dune", "media_type": "movie"},
    "media.progress": {"id": 1, "status": "completed", "rating_given": 9},
}

EXPANDED_ACTION_SAMPLES = {
    "task.update": {"id": 1, "title": "Updated"},
    "task.complete": {"id": 1},
    "task.delete": {"id": 1},
    "medication.delete": {"id": 1},
    "medication.update": {"id": 1, "notes": "Updated"},
    "medication.log.update": {"id": 1, "notes": "Updated"},
    "medication.log.delete": {"id": 1},
    "medication.plan.create": {"plan_name": "Morning", "medication_id": 1},
    "medication.plan.update": {"id": 1, "dosage": "2 tablets"},
    "medication.plan.delete": {"id": 1},
    "exercise.delete": {"id": 1},
    "exercise.update": {"id": 1, "equipment": "Barbell"},
    "training_set.update": {"id": 1, "description": "Updated"},
    "training_set.delete": {"id": 1},
    "workout.delete": {"id": 1},
    "workout.update": {"id": 1, "notes": "Updated"},
    "recipe.update": {"id": 1, "name": "New pasta"},
    "recipe.delete": {"id": 1},
    "recipe.ingredient.add": {"recipe_id": 1, "ingredient_id": 1, "quantity": 2, "unit": "cup"},
    "recipe.ingredient.remove": {"recipe_id": 1, "ingredient_id": 1},
    "ingredient.update": {"id": 1, "category": "Produce"},
    "ingredient.delete": {"id": 1},
    "inventory.adjust": {"inventory_id": 1, "quantity_delta": -1},
    "inventory.update": {"id": 1, "quantity": 5},
    "inventory.delete": {"id": 1},
    "meal.create": {"date": "2026-01-15", "meal_type": "dinner"},
    "meal.delete": {"id": 1},
    "meal.update": {"id": 1, "notes": "Updated"},
    "media.update": {"id": 1, "status": "watching"},
    "media.delete": {"id": 1},
}


def _row(data: dict) -> dict:
    return data


class _TrackingTransaction:
    def __init__(self):
        self.entered = False
        self.exited_with = None

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.exited_with = exc_type
        return False


class ApprovalWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        sys.path.insert(0, API_PATH)
        from app.routers import ai as ai_router

        self.ai_router = ai_router

    def test_direct_internal_mutation_http_route_is_removed(self):
        source = (ROOT / "api" / "app" / "routers" / "ai.py").read_text(encoding="utf-8")
        self.assertNotIn('@router.post("/internal/ai/actions")', source)
        self.assertIn('@router.post("/internal/ai/proposals"', source)

    async def test_internal_proposal_persists_without_executing_domain_action(self):
        transaction = _TrackingTransaction()
        conn = MagicMock()
        conn.transaction.return_value = transaction
        conn.fetchrow = AsyncMock(
            return_value={
                "request_id": "11111111-1111-1111-1111-111111111111",
                "status": "pending",
                "proposed_at": "2026-08-29T00:00:00Z",
                "decided_at": None,
            }
        )
        conn.executemany = AsyncMock()
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def fake_connection():
            yield conn

        request = self.ai_router.AIActionRequest(
            request_id="11111111-1111-1111-1111-111111111111",
            actions=[{"action": "task.create", "arguments": {"title": "Review me"}}],
        )
        with (
            patch.object(self.ai_router, "connection", fake_connection),
            patch.object(self.ai_router, "_execute_action", AsyncMock()) as execute,
        ):
            result = await self.ai_router.create_ai_proposal(
                request,
                x_omniflow_secret=self.ai_router.get_settings().service_secret,
            )

        self.assertEqual("pending", result["status"])
        self.assertTrue(transaction.entered)
        conn.executemany.assert_awaited_once()
        execute.assert_not_awaited()

    async def test_approval_executes_and_commits_proposal_status_together(self):
        transaction = _TrackingTransaction()
        conn = MagicMock()
        conn.transaction.return_value = transaction
        conn.execute = AsyncMock()

        @asynccontextmanager
        async def fake_connection():
            yield conn

        request_row = {
            "request_id": "22222222-2222-2222-2222-222222222222",
            "status": "pending",
            "context": {},
            "proposed_at": "2026-08-29T00:00:00Z",
            "decided_at": None,
        }
        action_rows = [
            {"action_index": 0, "action": "task.create", "arguments": {"title": "Approved"}}
        ]
        confirmation = {
            "success": True,
            "request_id": request_row["request_id"],
            "results": [{"audit_id": 7}],
            "audit_ids": [7],
        }
        with (
            patch.object(self.ai_router, "connection", fake_connection),
            patch.object(
                self.ai_router,
                "_load_proposal",
                AsyncMock(return_value=(request_row, action_rows)),
            ),
            patch.object(
                self.ai_router,
                "_run_action_batch",
                AsyncMock(return_value=confirmation),
            ) as execute,
        ):
            result = await self.ai_router.approve_ai_proposal(
                uuid4().__class__(request_row["request_id"])
            )

        self.assertEqual("committed", result["status"])
        self.assertTrue(transaction.entered)
        execute.assert_awaited_once()
        self.assertIn("status='committed'", conn.execute.await_args.args[0])

    async def test_rejection_records_decision_without_executing_actions(self):
        conn = MagicMock()
        conn.fetchrow = AsyncMock(
            return_value={
                "request_id": "33333333-3333-3333-3333-333333333333",
                "status": "rejected",
                "proposed_at": "2026-08-29T00:00:00Z",
                "decided_at": "2026-08-29T00:01:00Z",
            }
        )

        @asynccontextmanager
        async def fake_connection():
            yield conn

        with (
            patch.object(self.ai_router, "connection", fake_connection),
            patch.object(self.ai_router, "_execute_action", AsyncMock()) as execute,
        ):
            result = await self.ai_router.reject_ai_proposal(
                uuid4().__class__("33333333-3333-3333-3333-333333333333")
            )

        self.assertEqual("rejected", result["status"])
        self.assertIn("status='rejected'", conn.fetchrow.await_args.args[0])
        execute.assert_not_awaited()


class AllowlistTests(unittest.TestCase):
    def test_rejects_unknown_action(self):
        with self.assertRaises(ValidationError):
            AIActionRequest(
                request_id=str(uuid4()),
                action="finance.create",
                arguments={},
            )

    def test_all_registry_actions_are_allowlisted(self):
        for action in AI_WRITE_ACTIONS:
            AIActionRequest(
                request_id=str(uuid4()),
                action=action,
                arguments=EXPANDED_ACTION_SAMPLES.get(action, OLD_PARITY_ACTIONS.get(action, {"id": 1})),
            )

    def test_no_finance_write_actions(self):
        self.assertFalse(any(action.startswith("finance.") for action in AI_WRITE_ACTIONS))

    def test_focus_tracking_actions_are_not_allowlisted(self):
        self.assertEqual(41, len(AI_WRITE_ACTIONS))
        self.assertFalse(any(action.startswith("focus_tracking.") for action in AI_WRITE_ACTIONS))

    def test_every_user_module_has_create_update_and_delete_coverage(self):
        required_lifecycles = {
            "tasks": {"task.create", "task.update", "task.delete"},
            "medication catalog": {
                "medication.create", "medication.update", "medication.delete",
            },
            "medication plans": {
                "medication.plan.create", "medication.plan.update", "medication.plan.delete",
            },
            "medication logs": {
                "medication.log", "medication.log.update", "medication.log.delete",
            },
            "exercise catalog": {"exercise.create", "exercise.update", "exercise.delete"},
            "training sets": {
                "training_set.create", "training_set.update", "training_set.delete",
            },
            "workouts": {"workout.create", "workout.update", "workout.delete"},
            "recipes": {"recipe.create", "recipe.update", "recipe.delete"},
            "ingredients": {
                "ingredient.create", "ingredient.update", "ingredient.delete",
            },
            "inventory": {"inventory.upsert", "inventory.update", "inventory.delete"},
            "meals": {"meal.create", "meal.update", "meal.delete"},
            "media": {"media.create", "media.update", "media.delete"},
        }
        for module, actions in required_lifecycles.items():
            with self.subTest(module=module):
                self.assertLessEqual(actions, set(AI_WRITE_ACTIONS))

    def test_legacy_single_action_is_upgraded_to_ordered_batch(self):
        request = AIActionRequest(
            request_id=str(uuid4()),
            action="task.create",
            arguments={"title": "Buy milk"},
        )
        self.assertEqual(1, len(request.actions))
        self.assertEqual("task.create", request.actions[0].action)
        self.assertEqual({"title": "Buy milk"}, request.actions[0].arguments)
        self.assertEqual("task.create", request.action)

    def test_batch_is_bounded_and_rejects_mixed_legacy_shape(self):
        actions = [{"action": "task.create", "arguments": {"title": str(index)}} for index in range(21)]
        with self.assertRaises(ValidationError):
            AIActionRequest(request_id=str(uuid4()), actions=actions)
        with self.assertRaises(ValidationError):
            AIActionRequest(
                request_id=str(uuid4()),
                actions=[{"action": "task.create", "arguments": {"title": "x"}}],
                action="task.create",
                arguments={"title": "y"},
            )
        with self.assertRaises(ValidationError):
            AIActionRequest(
                request_id=str(uuid4()),
                actions=[{"action": "task.create", "arguments": {"title": "x"}}],
                action=None,
                arguments=None,
            )

    def test_context_is_allowlisted_and_requires_positive_ids(self):
        with self.assertRaises(ValidationError):
            AIActionRequest(
                request_id=str(uuid4()),
                actions=[{"action": "task.create", "arguments": {"title": "x"}}],
                context={"recipe_id": 0},
            )
        with self.assertRaises(ValidationError):
            AIActionRequest(
                request_id=str(uuid4()),
                actions=[{"action": "task.create", "arguments": {"title": "x"}}],
                context={"sql": "SELECT 1"},
            )

    def test_required_database_columns_reject_explicit_null_on_update(self):
        cases = [
            (TaskUpdate, {"title": None}),
            (RecipeUpdate, {"name": None}),
            (InventoryUpdate, {"quantity": None}),
            (MediaUpdate, {"status": None}),
        ]
        for model, payload in cases:
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValidationError):
                    model.model_validate(payload)

    def test_media_update_rejects_unknown_status(self):
        with self.assertRaises(ValidationError):
            MediaUpdate(status="finished")

    def test_exact_quantities_never_coerce_through_float(self):
        exact_quantity = Decimal("12345678.91")
        exact_weight = Decimal("123456.79")
        cases = (
            (
                InventoryCreate,
                {"name": "Oil", "quantity": str(exact_quantity), "unit": "ml"},
                "quantity",
                exact_quantity,
            ),
            (
                InventoryUpdate,
                {"min_quantity": str(exact_quantity)},
                "min_quantity",
                exact_quantity,
            ),
            (
                RecipeIngredientAdd,
                {"ingredient_id": 1, "quantity": str(exact_quantity), "unit": "g"},
                "quantity",
                exact_quantity,
            ),
            (
                WorkoutExercise,
                {"weight_kg": str(exact_weight)},
                "weight_kg",
                exact_weight,
            ),
        )
        for model, payload, field, exact in cases:
            with self.subTest(model=model.__name__, field=field):
                value = getattr(model.model_validate(payload), field)
                self.assertIsInstance(value, Decimal)
                self.assertEqual(exact, value)

    def test_decimal_constraints_match_postgresql_precision(self):
        invalid = (
            (InventoryCreate, {"name": "Oil", "quantity": "123456789.00", "unit": "ml"}),
            (InventoryUpdate, {"quantity": "0.001"}),
            (
                RecipeIngredientAdd,
                {"ingredient_id": 1, "quantity": "0.001", "unit": "g"},
            ),
            (WorkoutExercise, {"weight_kg": "1234567.00"}),
            (InventoryAdjust, {"inventory_id": 1, "quantity_delta": "123456789.00"}),
        )
        for model, payload in invalid:
            with self.subTest(model=model.__name__, payload=payload):
                with self.assertRaises(ValidationError):
                    model.model_validate(payload)

    def test_database_names_and_units_are_trimmed_and_non_blank(self):
        task = TaskCreate(title="  Write report  ")
        inventory = InventoryCreate(name="  Rice  ", quantity="1.00", unit="  kg  ")
        self.assertEqual("Write report", task.title)
        self.assertEqual("Rice", inventory.name)
        self.assertEqual("kg", inventory.unit)

        invalid = (
            (TaskCreate, {"title": "   "}),
            (MedicationCreate, {"name": "   "}),
            (ExerciseCreate, {"name": "Squat", "muscle_group": "   "}),
            (InventoryCreate, {"name": "Rice", "quantity": "1.00", "unit": "   "}),
        )
        for model, payload in invalid:
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValidationError):
                    model.model_validate(payload)


class ExecuteActionHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        sys.path.insert(0, API_PATH)
        from app.routers import ai as ai_router

        self.ai_router = ai_router

    async def test_old_parity_actions_smoke(self):
        cases = {
            "task.create": (_row({"id": 1, "title": "x"}), "tasks"),
            "medication.create": (_row({"id": 1, "name": "Med"}), "medications"),
            "medication.log": (_row({"id": 1, "plan_id": 1}), "medication_logs"),
            "exercise.create": (_row({"id": 1, "name": "Squat"}), "exercise_catalog"),
            "training_set.create": (None, "training_sets"),
            "workout.create": (None, "workout_sessions"),
            "recipe.create": (_row({"id": 1, "name": "Pasta"}), "recipes"),
            "ingredient.create": (_row({"id": 1, "name": "Tomato"}), "ingredients"),
            "inventory.upsert": (None, "inventory"),
            "media.create": (_row({"id": 1, "title": "Dune"}), "media_items"),
            "media.progress": (_row({"id": 1, "status": "completed"}), "media_items"),
        }
        for action, (row, table) in cases.items():
            conn = AsyncMock()
            if action == "medication.log":
                conn.fetchval.return_value = 1
                conn.fetchrow.return_value = _row({"id": 1, "plan_id": 1})
            elif action == "training_set.create":
                conn.fetchval.return_value = 1
                conn.fetchrow.return_value = _row({"id": 1, "name": "Leg Day"})
            elif action == "workout.create":
                conn.fetchval.side_effect = [1, None]
                conn.fetchrow.return_value = _row({"id": 1})
            elif action == "inventory.upsert":
                conn.fetchval.side_effect = [1, 2]
                conn.fetchrow.return_value = _row({"id": 2, "name": "Tomato", "quantity": 2})
            elif action == "media.progress":
                conn.fetchrow.side_effect = [
                    _row({"id": 1, "status": "watching"}),
                    _row({"id": 1, "status": "completed"}),
                ]
            else:
                conn.fetchrow.return_value = row
            result_table, entity_id, _, _ = await self.ai_router._execute_action(
                conn, action, OLD_PARITY_ACTIONS[action]
            )
            self.assertEqual(table, result_table, action)
            self.assertTrue(entity_id)

    async def test_strict_argument_registry_covers_allowlist(self):
        self.assertEqual(
            set(AI_WRITE_ACTIONS),
            set(self.ai_router._ACTION_ARGUMENT_KEYS),
        )
        from app.schemas import AIActionContext

        self.assertTrue(
            {
                context_key
                for context_key, _ in self.ai_router._RESULT_CONTEXT_IDS.values()
            }.issubset(AIActionContext.model_fields)
        )

    async def test_old_parity_task_create(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _row({"id": 42, "title": "Buy milk", "priority": "high"})
        table, entity_id, before, after = await self.ai_router._execute_action(
            conn, "task.create", {"title": "Buy milk", "priority": "high"}
        )
        self.assertEqual("tasks", table)
        self.assertEqual("42", entity_id)
        self.assertIsNone(before)
        self.assertEqual("Buy milk", after["title"])

    async def test_ai_action_arguments_canonicalize_display_case_enums(self):
        task = await self.ai_router._prepare_action_arguments(
            AsyncMock(),
            "task.create",
            {"title": "Give Interview", "priority": "High"},
        )
        self.assertEqual("high", task["priority"])

        meal = await self.ai_router._prepare_action_arguments(
            AsyncMock(),
            "meal.create",
            {"date": "2026-08-31", "meal_type": "Dinner"},
        )
        self.assertEqual("dinner", meal["meal_type"])

        recipe = await self.ai_router._prepare_action_arguments(
            AsyncMock(),
            "recipe.create",
            {"name": "Soup", "difficulty": "medium"},
        )
        self.assertEqual("Medium", recipe["difficulty"])

        media = await self.ai_router._prepare_action_arguments(
            AsyncMock(),
            "media.create",
            {"title": "Dune", "media_type": "TV Show", "status": "Plan-To-Watch"},
        )
        self.assertEqual("tv_show", media["media_type"])
        self.assertEqual("plan_to_watch", media["status"])

    async def test_old_parity_medication_log_resolves_plan(self):
        conn = AsyncMock()
        conn.fetchval.return_value = 7
        conn.fetchrow.return_value = _row({"id": 3, "plan_id": 7, "medication_name": "Vitamin D"})
        table, entity_id, before, after = await self.ai_router._execute_action(
            conn, "medication.log", {"medication_id": 2}
        )
        self.assertEqual("medication_logs", table)
        self.assertEqual("3", entity_id)
        conn.fetchval.assert_awaited()
        self.assertIn("active=TRUE", conn.fetchval.await_args.args[0])

    async def test_expanded_recipe_ingredient_add(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _row(
            {"recipe_id": 1, "ingredient_id": 2, "quantity": 2, "unit": "cup"}
        )
        table, entity_id, before, after = await self.ai_router._execute_action(
            conn,
            "recipe.ingredient.add",
            {"recipe_id": 1, "ingredient_id": 2, "quantity": 2, "unit": "cup"},
        )
        self.assertEqual("recipe_ingredients", table)
        self.assertEqual("1:2", entity_id)

    async def test_recursive_context_and_prior_action_references(self):
        prior = [
            {
                "entity_id": "12",
                "result": {"id": 12, "nested": {"value": "resolved"}},
            }
        ]
        resolved = self.ai_router._resolve_references(
            {
                "recipe_id": "$ref:context.recipe_id",
                "ingredient_id": "$ref:actions.0.result.id",
                "nested": ["$ref:actions.0.result.nested.value"],
            },
            {"recipe_id": 7},
            prior,
        )
        self.assertEqual(
            {"recipe_id": 7, "ingredient_id": 12, "nested": ["resolved"]},
            resolved,
        )

        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            self.ai_router._resolve_references(
                {"id": "$ref:actions.1.entity_id"},
                {},
                prior,
            )
        self.assertEqual(422, ctx.exception.status_code)

        with self.assertRaises(HTTPException) as malformed:
            self.ai_router._resolve_references(
                {"nested": ["$ref:actions.0.result.missing"]},
                {},
                prior,
            )
        self.assertEqual(422, malformed.exception.status_code)

    async def test_name_resolution_is_exact_and_ambiguity_safe(self):
        conn = AsyncMock()
        conn.fetch.side_effect = [
            [_row({"id": 3, "entity_name": "Pasta"})],
            [_row({"id": 5, "entity_name": "Olive Oil"})],
        ]
        resolved = await self.ai_router._prepare_action_arguments(
            conn,
            "recipe.ingredient.add",
            {
                "recipe_name": "pasta",
                "ingredient_name": "olive oil",
                "quantity": 2,
                "unit": "tbsp",
            },
        )
        self.assertEqual(3, resolved["recipe_id"])
        self.assertEqual(5, resolved["ingredient_id"])
        self.assertNotIn("recipe_name", resolved)
        self.assertNotIn("ingredient_name", resolved)

        ambiguous = AsyncMock()
        ambiguous.fetch.return_value = [
            _row({"id": 1, "entity_name": "Dinner"}),
            _row({"id": 2, "entity_name": "Dinner"}),
        ]
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await self.ai_router._prepare_action_arguments(
                ambiguous,
                "recipe.delete",
                {"recipe_name": "Dinner"},
            )
        self.assertEqual(409, ctx.exception.status_code)

        mismatch = AsyncMock()
        mismatch.fetchrow.return_value = _row({"id": 3, "entity_name": "Pasta"})
        with self.assertRaises(HTTPException) as mismatch_ctx:
            await self.ai_router._prepare_action_arguments(
                mismatch,
                "recipe.delete",
                {"id": 3, "recipe_name": "Soup"},
            )
        self.assertEqual(422, mismatch_ctx.exception.status_code)

    async def test_plain_ids_reject_booleans_fractions_and_nonpositive_values(self):
        from fastapi import HTTPException

        for invalid in (True, 1.5, 0, -1):
            with self.subTest(invalid=invalid):
                with self.assertRaises(HTTPException) as raised:
                    await self.ai_router._prepare_action_arguments(
                        AsyncMock(),
                        "task.delete",
                        {"id": invalid},
                    )
                self.assertEqual(422, raised.exception.status_code)

    async def test_inventory_selector_conflicts_are_rejected(self):
        from fastapi import HTTPException

        conn = AsyncMock()
        conn.fetchrow.return_value = _row(
            {"id": 4, "ingredient_id": 8, "name": "Rice"}
        )
        with self.assertRaises(HTTPException) as raised:
            await self.ai_router._prepare_action_arguments(
                conn,
                "inventory.update",
                {"id": 4, "ingredient_id": 9, "quantity": 2},
            )
        self.assertEqual(422, raised.exception.status_code)

    async def test_inventory_upsert_allows_a_new_name_but_optional_relation_does_not(self):
        conn = AsyncMock()
        conn.fetch.return_value = []
        resolved = await self.ai_router._prepare_action_arguments(
            conn,
            "inventory.upsert",
            {"name": "New ingredient", "quantity": 1, "unit": "piece"},
        )
        self.assertEqual("New ingredient", resolved["name"])

        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await self.ai_router._prepare_action_arguments(
                conn,
                "meal.create",
                {
                    "date": "2026-01-15",
                    "meal_type": "dinner",
                    "recipe_name": "Missing recipe",
                },
            )
        self.assertEqual(404, ctx.exception.status_code)

        missing_optional_selector = AsyncMock()
        missing_optional_selector.fetch.return_value = []
        with self.assertRaises(HTTPException) as ctx:
            await self.ai_router._prepare_action_arguments(
                missing_optional_selector,
                "meal.create",
                {
                    "date": "2026-01-15",
                    "meal_type": "dinner",
                    "recipe_name": "Missing recipe",
                },
            )
        self.assertEqual(404, ctx.exception.status_code)

    async def test_inventory_upsert_reuses_case_insensitive_ingredient_after_lock(self):
        conn = AsyncMock()
        conn.fetch.return_value = [_row({"id": 8, "name": "Olive Oil"})]
        conn.fetchrow.side_effect = [
            _row(
                {
                    "id": 4,
                    "ingredient_id": 8,
                    "name": "Olive Oil",
                    "quantity": Decimal("1.00"),
                }
            ),
            _row(
                {
                    "id": 4,
                    "ingredient_id": 8,
                    "name": "Olive Oil",
                    "quantity": Decimal("2.00"),
                }
            ),
        ]
        conn.fetchval.return_value = 4

        table, entity_id, before, after = await self.ai_router._execute_action(
            conn,
            "inventory.upsert",
            {"name": "olive oil", "quantity": "2.00", "unit": "tbsp"},
        )

        self.assertEqual("inventory", table)
        self.assertEqual("4", entity_id)
        self.assertEqual("Olive Oil", before["name"])
        self.assertEqual(Decimal("2.00"), after["quantity"])
        self.assertEqual(1, conn.fetchval.await_count)
        self.assertIn("INSERT INTO inventory", conn.fetchval.await_args.args[0])
        self.assertEqual(8, conn.fetchval.await_args.args[1])

    async def test_nested_exercise_names_bind_to_catalog_ids(self):
        conn = AsyncMock()
        conn.fetch.return_value = [_row({"id": 11, "entity_name": "Squat"})]
        resolved = await self.ai_router._prepare_action_arguments(
            conn,
            "workout.create",
            {
                "session_date": "2026-01-15",
                "exercises": [{"exercise_name": "squat", "sets_completed": 3}],
            },
        )
        self.assertEqual(11, resolved["exercises"][0]["exercise_id"])
        self.assertNotIn("exercise_name", resolved["exercises"][0])

    async def test_unsupported_top_level_and_nested_arguments_are_rejected(self):
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await self.ai_router._prepare_action_arguments(
                AsyncMock(),
                "task.create",
                {"title": "Safe", "sql": "SELECT 1"},
            )
        self.assertEqual(422, ctx.exception.status_code)

        conn = AsyncMock()
        conn.fetch.return_value = [_row({"id": 11, "entity_name": "Squat"})]
        with self.assertRaises(HTTPException) as nested_ctx:
            await self.ai_router._prepare_action_arguments(
                conn,
                "workout.create",
                {
                    "exercises": [
                        {"exercise_name": "Squat", "sets_completed": 1, "drop": True}
                    ]
                },
            )
        self.assertEqual(422, nested_ctx.exception.status_code)

    async def test_media_aliases_preserve_zero_and_reject_conflicts(self):
        conn = AsyncMock()
        conn.fetchrow.return_value = _row({"id": 4, "entity_name": "Dune"})
        resolved = await self.ai_router._prepare_action_arguments(
            conn,
            "media.progress",
            {"id": 4, "rating": 0, "rating_given": 0, "review_snapshot": ""},
        )
        self.assertEqual(0, resolved["rating"])
        self.assertEqual("", resolved["review"])
        self.assertNotIn("rating_given", resolved)
        self.assertNotIn("review_snapshot", resolved)

        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await self.ai_router._prepare_action_arguments(
                conn,
                "media.progress",
                {"id": 4, "rating": 8, "rating_given": 9},
            )
        self.assertEqual(422, ctx.exception.status_code)

    async def test_workout_explicit_name_and_zero_sets_are_preserved(self):
        conn = AsyncMock()
        conn.fetchval.side_effect = [17, "Squat"]
        conn.fetchrow.return_value = _row({"id": 17, "set_name": "Custom"})
        table, entity_id, _, after = await self.ai_router._execute_action(
            conn,
            "workout.create",
            {
                "training_set_id": 3,
                "name": "Custom",
                "session_date": "2026-01-15",
                "exercises": [
                    {
                        "exercise_id": 11,
                        "sets_completed": 0,
                        "sets": [{"reps": 5}],
                    }
                ],
            },
        )
        self.assertEqual("workout_sessions", table)
        self.assertEqual("17", entity_id)
        self.assertEqual("Custom", after["set_name"])
        self.assertEqual(2, conn.fetchval.await_count)
        workout_insert_args = conn.fetchval.await_args_list[0].args
        self.assertEqual("Custom", workout_insert_args[2])
        exercise_insert_args = conn.execute.await_args.args
        self.assertEqual(0, exercise_insert_args[4])

    async def test_media_progress_validates_combined_state_and_completion_transition(self):
        from datetime import datetime, timezone
        from fastapi import HTTPException

        completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)

        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _row(
                {
                    "id": 4,
                    "status": "watching",
                    "progress_current": 3,
                    "progress_total": 10,
                    "completion_date": None,
                }
            ),
            _row(
                {
                    "id": 4,
                    "status": "completed",
                    "progress_current": 3,
                    "progress_total": 10,
                    "completion_date": completed_at,
                }
            ),
        ]
        _, _, _, after = await self.ai_router._execute_action(
            conn,
            "media.progress",
            {"id": 4, "status": "completed", "progress_current": 3},
        )

        self.assertEqual("completed", after["status"])
        update_args = conn.fetchrow.await_args_list[1].args
        self.assertIn("completion_date", update_args[0])
        completion_values = [
            value for value in update_args[1:] if isinstance(value, datetime)
        ]
        self.assertEqual(1, len(completion_values))
        self.assertIsNotNone(completion_values[0].tzinfo)

        invalid = AsyncMock()
        invalid.fetchrow.return_value = _row(
            {
                "id": 4,
                "status": "watching",
                "progress_current": 8,
                "progress_total": 10,
                "completion_date": None,
            }
        )
        with self.assertRaises(HTTPException) as raised:
            await self.ai_router._execute_action(
                invalid,
                "media.update",
                {"id": 4, "progress_current": 11},
            )
        self.assertEqual(422, raised.exception.status_code)
        self.assertEqual(
            "progress_current cannot exceed progress_total",
            raised.exception.detail,
        )

    async def test_ai_media_create_stamps_only_completed_items(self):
        from datetime import datetime

        for status, should_stamp in (("completed", True), ("watching", False)):
            with self.subTest(status=status):
                conn = AsyncMock()
                conn.fetchrow.return_value = _row({"id": 4, "status": status})
                await self.ai_router._execute_action(
                    conn,
                    "media.create",
                    {"title": "Dune", "media_type": "book", "status": status},
                )
                completion_date = conn.fetchrow.await_args.args[-1]
                if should_stamp:
                    self.assertIsInstance(completion_date, datetime)
                    self.assertIsNotNone(completion_date.tzinfo)
                else:
                    self.assertIsNone(completion_date)

    async def test_expanded_delete_handlers_return_auditable_before_state(self):
        cases = (
            ("task.delete", {"id": 1}, "tasks", "1"),
            ("medication.delete", {"id": 1}, "medications", "1"),
            ("medication.plan.delete", {"id": 1}, "medication_plans", "1"),
            ("exercise.delete", {"id": 1}, "exercise_catalog", "1"),
            ("training_set.delete", {"id": 1}, "training_sets", "1"),
            ("workout.delete", {"id": 1}, "workout_sessions", "1"),
            ("recipe.delete", {"id": 1}, "recipes", "1"),
            (
                "recipe.ingredient.remove",
                {"recipe_id": 1, "ingredient_id": 2},
                "recipe_ingredients",
                "1:2",
            ),
            ("inventory.delete", {"id": 1}, "inventory", "1"),
            ("meal.delete", {"id": 1}, "meal_entries", "1"),
            ("media.delete", {"id": 1}, "media_items", "1"),
        )
        for action, arguments, expected_table, expected_id in cases:
            with self.subTest(action=action):
                conn = AsyncMock()
                conn.fetchrow.return_value = _row({"id": 1, **arguments})
                table, entity_id, before, after = await self.ai_router._execute_action(
                    conn,
                    action,
                    arguments,
                )
                self.assertEqual(expected_table, table)
                self.assertEqual(expected_id, entity_id)
                self.assertIsNotNone(before)
                self.assertIsNone(after)
                conn.execute.assert_awaited_once()

    async def test_expanded_handlers_report_missing_rows(self):
        from fastapi import HTTPException

        for action, arguments in (
            ("task.update", {"id": 1, "title": "Updated"}),
            ("task.complete", {"id": 1}),
            ("task.delete", {"id": 1}),
            ("medication.delete", {"id": 1}),
            ("medication.plan.delete", {"id": 1}),
            ("exercise.delete", {"id": 1}),
            ("training_set.delete", {"id": 1}),
            ("workout.delete", {"id": 1}),
            ("recipe.update", {"id": 1, "name": "Updated"}),
            ("recipe.delete", {"id": 1}),
            (
                "recipe.ingredient.remove",
                {"recipe_id": 1, "ingredient_id": 2},
            ),
            ("inventory.adjust", {"inventory_id": 1, "quantity_delta": -1}),
            ("inventory.update", {"id": 1, "quantity": 1}),
            ("inventory.delete", {"id": 1}),
            ("meal.delete", {"id": 1}),
            ("media.update", {"id": 1, "status": "watching"}),
            ("media.progress", {"id": 1, "status": "watching"}),
            ("media.delete", {"id": 1}),
        ):
            with self.subTest(action=action):
                conn = AsyncMock()
                conn.fetchrow.return_value = None
                with self.assertRaises(HTTPException) as raised:
                    await self.ai_router._execute_action(conn, action, arguments)
                self.assertEqual(404, raised.exception.status_code)

    async def test_inventory_adjust_is_guarded_and_returns_before_after(self):
        from fastapi import HTTPException

        conn = AsyncMock()
        conn.fetchrow.side_effect = [
            _row(
                {
                    "id": 4,
                    "ingredient_id": 8,
                    "name": "Rice",
                    "quantity": 5,
                    "unit": "kg",
                    "category": "Pantry",
                    "expiry_date": None,
                    "min_quantity": 1,
                }
            ),
            _row(
                {
                    "id": 4,
                    "ingredient_id": 8,
                    "name": "Rice",
                    "quantity": 3,
                    "unit": "kg",
                    "category": "Pantry",
                    "expiry_date": None,
                    "min_quantity": 1,
                }
            ),
        ]
        conn.fetchval.return_value = 4
        table, entity_id, before, after = await self.ai_router._execute_action(
            conn,
            "inventory.adjust",
            {"inventory_id": 4, "quantity_delta": -2, "unit": "kg"},
        )
        self.assertEqual("inventory", table)
        self.assertEqual("4", entity_id)
        self.assertEqual(5, before["quantity"])
        self.assertEqual(3, after["quantity"])
        update_query, inventory_id, quantity_delta = conn.fetchval.await_args.args
        self.assertIn("quantity+$2 >= 0", update_query)
        self.assertEqual(4, inventory_id)
        self.assertEqual(Decimal("-2"), quantity_delta)

        wrong_unit = AsyncMock()
        wrong_unit.fetchrow.return_value = _row(
            {"id": 4, "quantity": 5, "unit": "kg"}
        )
        with self.assertRaises(HTTPException) as unit_error:
            await self.ai_router._execute_action(
                wrong_unit,
                "inventory.adjust",
                {"inventory_id": 4, "quantity_delta": -2, "unit": "lb"},
            )
        self.assertEqual(422, unit_error.exception.status_code)
        wrong_unit.fetchval.assert_not_awaited()

        insufficient = AsyncMock()
        insufficient.fetchrow.return_value = _row(
            {"id": 4, "quantity": 1, "unit": "kg"}
        )
        insufficient.fetchval.return_value = None
        with self.assertRaises(HTTPException) as quantity_error:
            await self.ai_router._execute_action(
                insufficient,
                "inventory.adjust",
                {"inventory_id": 4, "quantity_delta": -2, "unit": "kg"},
            )
        self.assertEqual(422, quantity_error.exception.status_code)
        self.assertEqual(
            "Inventory adjustment would make quantity negative",
            quantity_error.exception.detail,
        )
        insufficient.fetchrow.assert_awaited_once()

    async def test_batch_executor_preserves_order_and_one_transaction(self):
        conn = AsyncMock()
        transaction = _TrackingTransaction()
        conn.transaction = MagicMock(return_value=transaction)
        conn.fetchval.side_effect = [101, 102]

        @asynccontextmanager
        async def fake_connection():
            yield conn

        execute = AsyncMock(
            side_effect=[
                (
                    "tasks",
                    "1",
                    None,
                    {
                        "id": 1,
                        "title": "First",
                        "exact_quantity": Decimal("1234567890.123456789"),
                    },
                ),
                ("tasks", "2", None, {"id": 2, "title": "Second"}),
            ]
        )
        request = AIActionRequest(
            request_id=str(uuid4()),
            actions=[
                {"action": "task.create", "arguments": {"title": "First"}},
                {"action": "task.create", "arguments": {"title": "Second"}},
            ],
        )
        with (
            patch.object(self.ai_router, "connection", fake_connection),
            patch.object(self.ai_router, "_execute_action", execute),
        ):
            result = await self.ai_router.execute_ai_action(
                request,
                x_omniflow_secret=self.ai_router.get_settings().service_secret,
            )

        self.assertTrue(transaction.entered)
        self.assertIsNone(transaction.exited_with)
        self.assertEqual(["task.create", "task.create"], [item["action"] for item in result["results"]])
        self.assertEqual([0, 1], [item["action_index"] for item in result["results"]])
        self.assertEqual([101, 102], result["audit_ids"])
        self.assertEqual(
            "1234567890.123456789",
            result["results"][0]["result"]["exact_quantity"],
        )
        self.assertEqual(2, conn.fetchval.await_count)
        audit_call_args = [call.args for call in conn.fetchval.await_args_list]
        self.assertEqual([0, 1], [args[2] for args in audit_call_args])

    async def test_batch_updates_context_for_later_action_references(self):
        conn = AsyncMock()
        transaction = _TrackingTransaction()
        conn.transaction = MagicMock(return_value=transaction)
        conn.fetchval.side_effect = [201, 202]

        @asynccontextmanager
        async def fake_connection():
            yield conn

        prepare = AsyncMock(side_effect=lambda _conn, _action, arguments: arguments)
        execute = AsyncMock(
            side_effect=[
                ("ingredients", "5", None, {"id": 5, "name": "Oil"}),
                (
                    "recipe_ingredients",
                    "7:5",
                    None,
                    {"recipe_id": 7, "ingredient_id": 5},
                ),
            ]
        )
        request = AIActionRequest(
            request_id=str(uuid4()),
            actions=[
                {"action": "ingredient.create", "arguments": {"name": "Oil"}},
                {
                    "action": "recipe.ingredient.add",
                    "arguments": {
                        "recipe_id": "$ref:context.recipe_id",
                        "ingredient_id": "$ref:actions.0.result.id",
                        "quantity": 1,
                        "unit": "tbsp",
                    },
                },
            ],
            context={"recipe_id": 7},
        )
        with (
            patch.object(self.ai_router, "connection", fake_connection),
            patch.object(self.ai_router, "_prepare_action_arguments", prepare),
            patch.object(self.ai_router, "_execute_action", execute),
        ):
            result = await self.ai_router.execute_ai_action(
                request,
                x_omniflow_secret=self.ai_router.get_settings().service_secret,
            )

        second_arguments = prepare.await_args_list[1].args[2]
        self.assertEqual(7, second_arguments["recipe_id"])
        self.assertEqual(5, second_arguments["ingredient_id"])
        self.assertEqual([201, 202], result["audit_ids"])

    async def test_audit_failure_escapes_and_rolls_back_the_domain_action(self):
        conn = AsyncMock()
        transaction = _TrackingTransaction()
        conn.transaction = MagicMock(return_value=transaction)
        conn.fetchval.side_effect = RuntimeError("audit insert failed")

        @asynccontextmanager
        async def fake_connection():
            yield conn

        request = AIActionRequest(
            request_id=str(uuid4()),
            action="task.create",
            arguments={"title": "Audited"},
        )
        with (
            patch.object(self.ai_router, "connection", fake_connection),
            patch.object(
                self.ai_router,
                "_execute_action",
                AsyncMock(
                    return_value=(
                        "tasks",
                        "1",
                        None,
                        {"id": 1, "title": "Audited"},
                    )
                ),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "audit insert failed"):
                await self.ai_router.execute_ai_action(
                    request,
                    x_omniflow_secret=self.ai_router.get_settings().service_secret,
                )

        self.assertIs(transaction.exited_with, RuntimeError)

    async def test_validation_error_escapes_transaction_before_becoming_422(self):
        conn = AsyncMock()
        transaction = _TrackingTransaction()
        conn.transaction = MagicMock(return_value=transaction)
        validation_error = None
        try:
            TaskCreate.model_validate({"title": ""})
        except ValidationError as exc:
            validation_error = exc
        self.assertIsNotNone(validation_error)

        @asynccontextmanager
        async def fake_connection():
            yield conn

        request = AIActionRequest(
            request_id=str(uuid4()),
            actions=[{"action": "task.create", "arguments": {"title": ""}}],
        )
        from fastapi import HTTPException

        with (
            patch.object(self.ai_router, "connection", fake_connection),
            patch.object(
                self.ai_router,
                "_execute_action",
                AsyncMock(side_effect=validation_error),
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await self.ai_router.execute_ai_action(
                    request,
                    x_omniflow_secret=self.ai_router.get_settings().service_secret,
                )
        self.assertEqual(422, ctx.exception.status_code)
        self.assertIs(transaction.exited_with, ValidationError)

    async def test_internal_action_helper_rejects_missing_and_incorrect_secrets(self):
        from fastapi import HTTPException

        request = AIActionRequest(
            request_id=str(uuid4()),
            action="task.delete",
            arguments={"id": 1},
        )
        for supplied in (None, "incorrect-secret"):
            with self.subTest(supplied=supplied):
                with self.assertRaises(HTTPException) as raised:
                    await self.ai_router.execute_ai_action(
                        request,
                        x_omniflow_secret=supplied,
                    )
                self.assertEqual(401, raised.exception.status_code)

    async def test_rejects_unknown_handler_action(self):
        conn = AsyncMock()
        from fastapi import HTTPException

        with self.assertRaises(HTTPException) as ctx:
            await self.ai_router._execute_action(conn, "sql.execute", {"sql": "DROP TABLE tasks"})
        self.assertEqual(422, ctx.exception.status_code)


@unittest.skipUnless(
    os.getenv("RUN_DB_TESTS") == "1",
    "Set RUN_DB_TESTS=1 with a running PostgreSQL stack to run integration tests",
)
class AIActionIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        sys.path.insert(0, API_PATH)
        from app.db import close_pool, open_pool
        from app.routers.ai import execute_ai_action
        from app.schemas import AIActionRequest

        self.execute = execute_ai_action
        self.AIActionRequest = AIActionRequest
        await open_pool()

    async def asyncTearDown(self):
        from app.db import close_pool

        await close_pool()

    async def _run(self, action: str, arguments: dict):
        from app.settings import get_settings

        request = self.AIActionRequest(
            request_id=str(uuid4()),
            action=action,
            arguments=arguments,
        )
        return await self.execute(
            request,
            x_omniflow_secret=get_settings().service_secret,
        )

    async def _run_batch(self, request_id, actions, context=None):
        from app.settings import get_settings

        request = self.AIActionRequest(
            request_id=request_id,
            actions=actions,
            context=context or {},
        )
        return await self.execute(
            request,
            x_omniflow_secret=get_settings().service_secret,
        )

    async def test_task_create_writes_audit(self):
        title = f"ai-test-{uuid4()}"
        result = await self._run("task.create", {"title": title, "priority": "low"})
        self.assertTrue(result["success"])
        self.assertEqual("task.create", result["action"])
        self.assertIsNotNone(result["audit_id"])
        await self._run("task.delete", {"id": int(result["entity_id"])})

    async def test_pending_proposal_requires_explicit_approval(self):
        from app.db import connection
        from app.routers.ai import approve_ai_proposal, create_ai_proposal
        from app.settings import get_settings

        request_id = uuid4()
        title = f"ai-approval-{request_id}"
        request = self.AIActionRequest(
            request_id=request_id,
            action="task.create",
            arguments={"title": title},
        )
        proposal = await create_ai_proposal(
            request,
            x_omniflow_secret=get_settings().service_secret,
        )
        self.assertEqual("pending", proposal["status"])
        async with connection() as conn:
            self.assertEqual(
                0,
                await conn.fetchval("SELECT count(*) FROM tasks WHERE title=$1", title),
            )
            self.assertEqual(
                "pending",
                await conn.fetchval(
                    "SELECT status FROM ai_action_requests WHERE request_id=$1",
                    request_id,
                ),
            )

        result = await approve_ai_proposal(request_id)
        self.assertEqual("committed", result["status"])
        async with connection() as conn:
            task_id = await conn.fetchval("SELECT id FROM tasks WHERE title=$1", title)
            self.assertIsNotNone(task_id)
            self.assertEqual(
                "committed",
                await conn.fetchval(
                    "SELECT status FROM ai_action_requests WHERE request_id=$1",
                    request_id,
                ),
            )
            await conn.execute("DELETE FROM tasks WHERE id=$1", task_id)
            await conn.execute("DELETE FROM ai_mutation_audit WHERE request_id=$1", request_id)
            await conn.execute("DELETE FROM ai_action_requests WHERE request_id=$1", request_id)

    async def test_new_crud_actions_cover_medication_gym_ingredient_and_meal_entities(self):
        from app.db import connection

        marker = str(uuid4())
        async with connection() as conn:
            async with conn.transaction():
                medication_id = await conn.fetchval(
                    "INSERT INTO medications(name) VALUES($1) RETURNING id",
                    f"Medication {marker}",
                )
                plan_id = await conn.fetchval(
                    """INSERT INTO medication_plans(plan_name,medication_id)
                       VALUES($1,$2) RETURNING id""",
                    f"Plan {marker}",
                    medication_id,
                )
                log_id = await conn.fetchval(
                    "INSERT INTO medication_logs(plan_id) VALUES($1) RETURNING id",
                    plan_id,
                )
                exercise_id = await conn.fetchval(
                    """INSERT INTO exercise_catalog(name,muscle_group)
                       VALUES($1,'Other') RETURNING id""",
                    f"Exercise {marker}",
                )
                set_id = await conn.fetchval(
                    "INSERT INTO training_sets(name) VALUES($1) RETURNING id",
                    f"Set {marker}",
                )
                workout_id = await conn.fetchval(
                    """INSERT INTO workout_sessions(set_name,session_date)
                       VALUES($1,CURRENT_DATE) RETURNING id""",
                    f"Workout {marker}",
                )
                ingredient_id = await conn.fetchval(
                    "INSERT INTO ingredients(name) VALUES($1) RETURNING id",
                    f"Ingredient {marker}",
                )
                recipe_id = await conn.fetchval(
                    "INSERT INTO recipes(name) VALUES($1) RETURNING id",
                    f"Recipe {marker}",
                )
                meal_id = await conn.fetchval(
                    """INSERT INTO meal_entries(meal_date,meal_type,recipe_id)
                       VALUES(CURRENT_DATE,'dinner',$1) RETURNING id""",
                    recipe_id,
                )

        updates = (
            ("medication.update", {"id": medication_id, "notes": "updated"}, "notes"),
            ("medication.log.update", {"id": log_id, "notes": "updated"}, "notes"),
            ("medication.plan.update", {"id": plan_id, "dosage": "updated"}, "dosage"),
            ("exercise.update", {"id": exercise_id, "equipment": "updated"}, "equipment"),
            ("training_set.update", {"id": set_id, "description": "updated"}, "description"),
            ("workout.update", {"id": workout_id, "notes": "updated"}, "notes"),
            ("ingredient.update", {"id": ingredient_id, "category": "updated"}, "category"),
            ("meal.update", {"id": meal_id, "notes": "updated"}, "notes"),
        )
        for action, arguments, updated_field in updates:
            with self.subTest(action=action):
                result = await self._run(action, arguments)
                self.assertTrue(result["success"])
                self.assertEqual("updated", result["result"][updated_field])

        deletes = (
            ("medication.log.delete", {"id": log_id}),
            ("workout.delete", {"id": workout_id}),
            ("training_set.delete", {"id": set_id}),
            ("exercise.delete", {"id": exercise_id}),
            ("meal.delete", {"id": meal_id}),
            ("ingredient.delete", {"id": ingredient_id}),
            ("medication.plan.delete", {"id": plan_id}),
            ("medication.delete", {"id": medication_id}),
        )
        for action, arguments in deletes:
            with self.subTest(action=action):
                self.assertTrue((await self._run(action, arguments))["success"])
        async with connection() as conn:
            await conn.execute("DELETE FROM recipes WHERE id=$1", recipe_id)

    async def test_late_validation_failure_rolls_back_actions_and_audits(self):
        from fastapi import HTTPException
        from app.db import connection

        request_id = uuid4()
        title = f"ai-rollback-{request_id}"
        with self.assertRaises(HTTPException) as ctx:
            await self._run_batch(
                request_id,
                [
                    {"action": "task.create", "arguments": {"title": title}},
                    {
                        "action": "task.update",
                        "arguments": {
                            "id": "$ref:actions.0.entity_id",
                            "priority": None,
                        },
                    },
                ],
            )
        self.assertEqual(422, ctx.exception.status_code)
        self.assertEqual(1, ctx.exception.detail["action_index"])
        async with connection() as conn:
            task_count = await conn.fetchval(
                "SELECT count(*) FROM tasks WHERE title=$1",
                title,
            )
            audit_count = await conn.fetchval(
                "SELECT count(*) FROM ai_mutation_audit WHERE request_id=$1",
                request_id,
            )
        self.assertEqual(0, task_count)
        self.assertEqual(0, audit_count)

    async def test_late_media_progress_failure_rolls_back_create_and_audit(self):
        from fastapi import HTTPException
        from app.db import connection

        request_id = uuid4()
        title = f"ai-media-rollback-{request_id}"
        with self.assertRaises(HTTPException) as raised:
            await self._run_batch(
                request_id,
                [
                    {
                        "action": "media.create",
                        "arguments": {
                            "title": title,
                            "media_type": "movie",
                            "status": "watching",
                        },
                    },
                    {
                        "action": "media.update",
                        "arguments": {
                            "id": "$ref:actions.0.entity_id",
                            "progress_current": -1,
                        },
                    },
                ],
            )
        self.assertEqual(422, raised.exception.status_code)
        self.assertEqual(1, raised.exception.detail["action_index"])
        async with connection() as conn:
            media_count = await conn.fetchval(
                "SELECT count(*) FROM media_items WHERE title=$1",
                title,
            )
            audit_count = await conn.fetchval(
                "SELECT count(*) FROM ai_mutation_audit WHERE request_id=$1",
                request_id,
            )
        self.assertEqual(0, media_count)
        self.assertEqual(0, audit_count)

    async def test_audit_insert_failure_rolls_back_real_domain_mutation(self):
        from app.db import connection as real_connection
        from app.routers import ai as ai_router
        from app.settings import get_settings

        request_id = uuid4()
        title = f"ai-audit-rollback-{request_id}"

        class AuditFailingConnection:
            def __init__(self, conn):
                self._conn = conn

            def __getattr__(self, name):
                return getattr(self._conn, name)

            async def fetchval(self, query, *args):
                if "INSERT INTO ai_mutation_audit" in query:
                    raise RuntimeError("forced audit insert failure")
                return await self._conn.fetchval(query, *args)

        @asynccontextmanager
        async def failing_connection():
            async with real_connection() as conn:
                yield AuditFailingConnection(conn)

        request = self.AIActionRequest(
            request_id=request_id,
            action="task.create",
            arguments={"title": title},
        )
        with patch.object(ai_router, "connection", failing_connection):
            with self.assertRaisesRegex(RuntimeError, "forced audit insert failure"):
                await self.execute(
                    request,
                    x_omniflow_secret=get_settings().service_secret,
                )

        async with real_connection() as conn:
            task_count = await conn.fetchval(
                "SELECT count(*) FROM tasks WHERE title=$1",
                title,
            )
            audit_count = await conn.fetchval(
                "SELECT count(*) FROM ai_mutation_audit WHERE request_id=$1",
                request_id,
            )
        self.assertEqual(0, task_count)
        self.assertEqual(0, audit_count)

    async def test_composite_creates_and_binds_ingredient_atomically(self):
        from app.db import connection

        request_id = uuid4()
        recipe_name = f"ai-composite-recipe-{request_id}"
        ingredient_name = f"ai-composite-ingredient-{request_id}"
        async with connection() as conn:
            recipe_id = await conn.fetchval(
                "INSERT INTO recipes(name) VALUES($1) RETURNING id",
                recipe_name,
            )

        try:
            result = await self._run_batch(
                request_id,
                [
                    {
                        "action": "ingredient.create",
                        "arguments": {"name": ingredient_name},
                    },
                    {
                        "action": "recipe.ingredient.add",
                        "arguments": {
                            "recipe_id": "$ref:context.recipe_id",
                            "ingredient_name": ingredient_name,
                            "quantity": 2,
                            "unit": "tbsp",
                        },
                    },
                ],
                context={"recipe_id": recipe_id},
            )
            self.assertEqual([0, 1], [item["action_index"] for item in result["results"]])
            self.assertEqual(
                ["ingredient.create", "recipe.ingredient.add"],
                [item["action"] for item in result["results"]],
            )
            self.assertEqual(2, len(result["audit_ids"]))

            async with connection() as conn:
                bound = await conn.fetchval(
                    """SELECT EXISTS(
                         SELECT 1 FROM recipe_ingredients ri
                         JOIN ingredients i ON i.id=ri.ingredient_id
                         WHERE ri.recipe_id=$1 AND i.name=$2
                       )""",
                    recipe_id,
                    ingredient_name,
                )
                audit_order = await conn.fetch(
                    """SELECT action_index,action FROM ai_mutation_audit
                       WHERE request_id=$1 ORDER BY action_index""",
                    request_id,
                )
            self.assertTrue(bound)
            self.assertEqual(
                [(0, "ingredient.create"), (1, "recipe.ingredient.add")],
                [(row["action_index"], row["action"]) for row in audit_order],
            )
        finally:
            async with connection() as conn:
                async with conn.transaction():
                    await conn.execute("DELETE FROM recipes WHERE id=$1", recipe_id)
                    await conn.execute(
                        "DELETE FROM ingredients WHERE name=$1",
                        ingredient_name,
                    )
                    await conn.execute(
                        "DELETE FROM ai_mutation_audit WHERE request_id=$1",
                        request_id,
                    )


if __name__ == "__main__":
    unittest.main()
