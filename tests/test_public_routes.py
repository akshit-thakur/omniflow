from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
API_PATH = str(ROOT / "api")
sys.path.insert(0, API_PATH)

from app.routers import gym, kitchen, media, medications, tasks  # noqa: E402
from app.schemas import (  # noqa: E402
    BulkMedia,
    ExerciseCreate,
    MediaCreate,
    MediaUpdate,
    MedicationPlanCreate,
    MealBatchRequest,
    TaskUpdate,
    WorkoutCreate,
)


def _connection_manager(conn):
    @asynccontextmanager
    async def manager():
        yield conn

    return manager


def _transaction_manager():
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=manager)
    manager.__aexit__ = AsyncMock(return_value=False)
    return manager


def _connection():
    conn = MagicMock()
    conn.fetch = AsyncMock()
    conn.fetchrow = AsyncMock()
    conn.fetchval = AsyncMock()
    conn.execute = AsyncMock()
    conn.executemany = AsyncMock()
    conn.transaction = MagicMock()
    return conn


class KitchenRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_availability_handles_sufficient_low_and_mismatched_units(self):
        conn = _connection()
        conn.fetchval.return_value = True
        conn.fetch.return_value = [
            {
                "ingredient_name": "Rice",
                "needed_quantity": 1,
                "needed_unit": "kg",
                "inventory_quantity": 2,
                "inventory_unit": "KG",
            },
            {
                "ingredient_name": "Oil",
                "needed_quantity": 2,
                "needed_unit": "l",
                "inventory_quantity": 1,
                "inventory_unit": "l",
            },
            {
                "ingredient_name": "Salt",
                "needed_quantity": 1,
                "needed_unit": "kg",
                "inventory_quantity": 100,
                "inventory_unit": "g",
            },
        ]
        with patch.object(kitchen, "connection", _connection_manager(conn)):
            result = await kitchen.recipe_availability(1)

        self.assertFalse(result["can_make"])
        self.assertEqual(["Rice"], [item["ingredient_name"] for item in result["available"]])
        self.assertEqual(["Oil"], [item["ingredient_name"] for item in result["low"]])
        self.assertEqual(["Salt"], [item["ingredient_name"] for item in result["missing"]])

    async def test_availability_rejects_missing_recipe(self):
        conn = _connection()
        conn.fetchval.return_value = False
        with patch.object(kitchen, "connection", _connection_manager(conn)):
            with self.assertRaisesRegex(Exception, "Recipe not found"):
                await kitchen.recipe_availability(99)

    async def test_meal_batch_uses_one_transaction_and_applies_all_operations(self):
        conn = _connection()
        conn.transaction.return_value = _transaction_manager()
        conn.fetchval.return_value = 7
        body = MealBatchRequest.model_validate({
            "items": [{"id": 7, "date": "2026-09-09", "meal_type": "lunch", "recipe_id": None, "notes": "Updated"}],
            "delete_ids": [8],
        })
        with patch.object(kitchen, "connection", _connection_manager(conn)):
            result = await kitchen.save_meal_batch(body)

        self.assertEqual({"status": "saved", "updated": 1, "created": 0, "deleted": 1}, result)
        conn.transaction.assert_called_once_with()
        conn.execute.assert_awaited_once()
        conn.fetchval.assert_awaited_once()


class GymRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_update_exercise_returns_updated_row(self):
        conn = _connection()
        conn.fetchrow.return_value = {
            "id": 7,
            "name": "Bench Press",
            "muscle_group": "Chest",
            "equipment": "Barbell",
            "description": "Flat bench",
        }
        body = ExerciseCreate(
            name="Bench Press",
            muscle_group="Chest",
            equipment="Barbell",
            description="Flat bench",
        )
        with patch.object(gym, "connection", _connection_manager(conn)):
            result = await gym.update_exercise(7, body)

        self.assertEqual("Bench Press", result["name"])
        self.assertIn("UPDATE exercise_catalog", conn.fetchrow.await_args.args[0])
        self.assertEqual(
            (7, "Bench Press", "Chest", "Barbell", "Flat bench"),
            conn.fetchrow.await_args.args[1:],
        )

    async def test_update_exercise_rejects_missing_row(self):
        conn = _connection()
        conn.fetchrow.return_value = None
        body = ExerciseCreate(name="Bench Press", muscle_group="Chest")
        with patch.object(gym, "connection", _connection_manager(conn)):
            with self.assertRaisesRegex(Exception, "Exercise not found"):
                await gym.update_exercise(7, body)

    async def test_workout_preserves_explicit_name_and_zero_sets(self):
        conn = _connection()
        conn.transaction.return_value = _transaction_manager()
        conn.fetchval.return_value = 17
        conn.fetchrow.return_value = {
            "id": 17,
            "training_set_id": 3,
            "set_name": "Custom Session",
            "session_date": "2026-08-25",
            "duration_minutes": None,
            "notes": None,
        }
        conn.fetch.return_value = []
        body = WorkoutCreate(
            training_set_id=3,
            name="Custom Session",
            session_date="2026-08-25",
            exercises=[{"exercise_name": "Squat", "sets_completed": 0, "sets": [{"reps": 5}]}],
        )
        with patch.object(gym, "connection", _connection_manager(conn)):
            result = await gym.create_history(body)

        self.assertEqual("Custom Session", result["set_name"])
        self.assertEqual(1, conn.fetchval.await_count)
        self.assertEqual(0, conn.execute.await_args.args[4])

    async def test_workout_uses_template_name_and_derives_omitted_sets(self):
        conn = _connection()
        conn.transaction.return_value = _transaction_manager()
        conn.fetchval.side_effect = ["Template Session", 18]
        conn.fetchrow.return_value = {
            "id": 18,
            "training_set_id": 3,
            "set_name": "Template Session",
            "session_date": "2026-08-25",
            "duration_minutes": None,
            "notes": None,
        }
        conn.fetch.return_value = []
        body = WorkoutCreate(
            training_set_id=3,
            session_date="2026-08-25",
            exercises=[
                {
                    "exercise_name": "Squat",
                    "sets": [{"reps": 5}, {"reps": 5}],
                }
            ],
        )
        with patch.object(gym, "connection", _connection_manager(conn)):
            result = await gym.create_history(body)

        self.assertEqual("Template Session", result["set_name"])
        workout_insert = conn.fetchval.await_args_list[1].args
        self.assertEqual("Template Session", workout_insert[2])
        self.assertEqual(2, conn.execute.await_args.args[4])

    async def test_workout_requires_a_resolvable_exercise(self):
        conn = _connection()
        transaction = _transaction_manager()
        conn.transaction.return_value = transaction
        conn.fetchval.return_value = 17
        body = WorkoutCreate(
            session_date="2026-08-25",
            exercises=[{}],
        )
        with patch.object(gym, "connection", _connection_manager(conn)):
            with self.assertRaisesRegex(Exception, "valid exercise"):
                await gym.create_history(body)

        self.assertIsNotNone(transaction.__aexit__.await_args.args[0])
        conn.execute.assert_not_awaited()


class MediaRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_completed_create_sets_completion_timestamp(self):
        conn = _connection()
        conn.fetchrow.return_value = {"id": 1, "status": "completed"}
        with patch.object(media, "connection", _connection_manager(conn)):
            result = await media.create_media(
                MediaCreate(title="Dune", media_type="book", status="completed")
            )

        self.assertEqual("completed", result["status"])
        completion_date = conn.fetchrow.await_args.args[-1]
        self.assertIsInstance(completion_date, datetime)
        self.assertIsNotNone(completion_date.tzinfo)

    async def test_bulk_create_applies_completion_rule_to_each_item(self):
        conn = _connection()
        conn.transaction.return_value = _transaction_manager()
        conn.fetchrow.side_effect = [
            {"id": 1, "status": "completed"},
            {"id": 2, "status": "watching"},
        ]
        body = BulkMedia(
            items=[
                {"title": "Done", "media_type": "book", "status": "completed"},
                {"title": "Started", "media_type": "movie", "status": "watching"},
            ]
        )
        with patch.object(media, "connection", _connection_manager(conn)):
            result = await media.bulk_media(body)

        self.assertEqual(2, result["created"])
        first_completion = conn.fetchrow.await_args_list[0].args[-1]
        second_completion = conn.fetchrow.await_args_list[1].args[-1]
        self.assertIsInstance(first_completion, datetime)
        self.assertIsNone(second_completion)

    async def test_completed_update_preserves_existing_timestamp(self):
        completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        before = {
            "id": 1,
            "status": "completed",
            "completion_date": completed_at,
            "progress_current": 10,
            "progress_total": 10,
        }
        after = {**before, "notes": "still done"}
        conn = _connection()
        conn.transaction.return_value = _transaction_manager()
        conn.fetchrow.side_effect = [before, after]
        with patch.object(media, "connection", _connection_manager(conn)):
            result = await media.update_media(
                1,
                MediaUpdate(status="completed", notes="still done"),
            )

        self.assertEqual(completed_at, result["completion_date"])
        self.assertIn(completed_at, conn.fetchrow.await_args.args)

    async def test_transition_out_of_completed_clears_timestamp(self):
        completed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        before = {
            "id": 1,
            "status": "completed",
            "completion_date": completed_at,
            "progress_current": 10,
            "progress_total": 10,
        }
        after = {**before, "status": "watching", "completion_date": None}
        conn = _connection()
        conn.transaction.return_value = _transaction_manager()
        conn.fetchrow.side_effect = [before, after]
        with patch.object(media, "connection", _connection_manager(conn)):
            result = await media.update_media(1, MediaUpdate(status="watching"))

        self.assertIsNone(result["completion_date"])
        self.assertIn(None, conn.fetchrow.await_args.args)

    async def test_partial_progress_rejects_current_above_stored_total(self):
        conn = _connection()
        conn.transaction.return_value = _transaction_manager()
        conn.fetchrow.return_value = {
            "id": 1,
            "status": "watching",
            "completion_date": None,
            "progress_current": 5,
            "progress_total": 10,
        }
        with patch.object(media, "connection", _connection_manager(conn)):
            with self.assertRaisesRegex(Exception, "cannot exceed"):
                await media.update_media(1, MediaUpdate(progress_current=11))

        self.assertEqual(1, conn.fetchrow.await_count)
        self.assertIn("SELECT", conn.fetchrow.await_args.args[0])


class TaskRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_update_returns_current_row(self):
        conn = _connection()
        conn.fetchrow.return_value = {"id": 1, "title": "Current"}
        with patch.object(tasks, "connection", _connection_manager(conn)):
            result = await tasks.update_task(1, TaskUpdate())
        self.assertEqual("Current", result["title"])

    async def test_update_not_found_is_reported(self):
        conn = _connection()
        conn.fetchrow.return_value = None
        with patch.object(tasks, "connection", _connection_manager(conn)):
            with self.assertRaisesRegex(Exception, "Task not found"):
                await tasks.update_task(1, TaskUpdate(title="Updated"))


class MedicationRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_plan_create_writes_bounded_schedule_and_returns_joined_row(self):
        conn = _connection()
        conn.transaction.return_value = _transaction_manager()
        conn.fetchval.return_value = 7
        conn.fetchrow.return_value = {
            "id": 7,
            "plan_name": "Morning",
            "medication_id": 2,
            "schedule_times": ["08:00"],
        }
        body = MedicationPlanCreate(
            plan_name="Morning",
            medication_id=2,
            schedule_times=["08:00"],
        )
        with patch.object(medications, "connection", _connection_manager(conn)):
            result = await medications.create_plan(body)

        self.assertEqual(7, result["id"])
        conn.executemany.assert_awaited_once()
        self.assertEqual(7, conn.executemany.await_args.args[1][0][0])

    async def test_plan_create_propagates_database_failure_outside_transaction(self):
        conn = _connection()
        transaction = _transaction_manager()
        conn.transaction.return_value = transaction
        conn.fetchval.side_effect = RuntimeError("missing medication")
        body = MedicationPlanCreate(plan_name="Morning", medication_id=2)
        with patch.object(medications, "connection", _connection_manager(conn)):
            with self.assertRaisesRegex(RuntimeError, "missing medication"):
                await medications.create_plan(body)

        self.assertIs(transaction.__aexit__.await_args.args[0], RuntimeError)
        conn.executemany.assert_not_awaited()
        conn.fetchrow.assert_not_awaited()


@unittest.skipUnless(
    os.getenv("RUN_DB_TESTS") == "1",
    "Set RUN_DB_TESTS=1 with a running PostgreSQL stack to run integration tests",
)
class PublicMutationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                del sys.modules[name]
        while API_PATH in sys.path:
            sys.path.remove(API_PATH)
        sys.path.insert(0, API_PATH)
        from app.db import open_pool
        from app.routers import gym as isolated_gym
        from app.schemas import WorkoutCreate as IsolatedWorkoutCreate

        self.gym = isolated_gym
        self.WorkoutCreate = IsolatedWorkoutCreate
        self.workout_name = f"public-workout-rollback-{uuid4()}"
        await open_pool()

    async def asyncTearDown(self):
        from app.db import close_pool, connection

        try:
            async with connection() as conn:
                await conn.execute(
                    "DELETE FROM workout_sessions WHERE set_name=$1",
                    self.workout_name,
                )
        finally:
            await close_pool()
            while API_PATH in sys.path:
                sys.path.remove(API_PATH)
            for name in list(sys.modules):
                if name == "app" or name.startswith("app."):
                    del sys.modules[name]

    async def test_invalid_exercise_rolls_back_inserted_workout(self):
        from fastapi import HTTPException
        from app.db import connection

        body = self.WorkoutCreate(
            name=self.workout_name,
            session_date="2026-08-25",
            exercises=[{}],
        )
        with self.assertRaises(HTTPException) as raised:
            await self.gym.create_history(body)

        self.assertEqual(422, raised.exception.status_code)
        async with connection() as conn:
            count = await conn.fetchval(
                "SELECT count(*) FROM workout_sessions WHERE set_name=$1",
                self.workout_name,
            )
        self.assertEqual(0, count)


if __name__ == "__main__":
    unittest.main()
