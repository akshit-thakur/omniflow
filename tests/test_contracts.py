from decimal import Decimal
import httpx
import json
import sys
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from app.main import app  # noqa: E402
from app import db as api_db  # noqa: E402
from app.routers import ai as ai_router  # noqa: E402
from app.routers import backups, gym, kitchen  # noqa: E402
from app.schemas import (  # noqa: E402
    AI_WRITE_ACTIONS,
    AIActionRequest,
    BulkMedia,
    ChatRequest,
    InventoryCreate,
    MediaCreate,
    MediaUpdate,
    MedicationPlanCreate,
    MealCreate,
    RecipeCreate,
    TaskCreate,
    TaskUpdate,
    TrainingSetCreate,
    WorkoutCreate,
    WorkoutExercise,
)
from pydantic import ValidationError  # noqa: E402


class FrontendContractTests(unittest.TestCase):
    def test_chat_renders_the_grounded_answer_without_dumping_retrieval_rows(self):
        source = (ROOT / "frontend" / "src" / "components" / "ChatBubble.tsx").read_text()

        self.assertNotIn("aiResponse.results.map", source)
        self.assertNotIn("formatResultItem", source)
        self.assertIn("/api/ai/agent/chat/stream", source)
        self.assertIn("response.body.getReader()", source)

    def test_chat_formats_object_shaped_approval_errors(self):
        source = (ROOT / "frontend" / "src" / "components" / "ChatBubble.tsx").read_text()

        self.assertIn("const formatErrorDetail", source)
        self.assertIn("Array.isArray(record.errors)", source)
        self.assertIn("formatErrorDetail(payload.detail || payload.error", source)
        self.assertNotIn("throw new Error(payload.detail || payload.error", source)

    def test_all_frontend_routes_exist(self):
        route_methods = {"get", "post", "put", "patch", "delete", "options", "head"}
        actual = {
            (method.upper(), path)
            for path, operations in app.openapi()["paths"].items()
            for method in operations
            if method in route_methods
        }
        expected = {
            ("GET", "/api/tasks/"),
            ("POST", "/api/tasks/"),
            ("GET", "/api/tasks/{task_id}"),
            ("PUT", "/api/tasks/{task_id}"),
            ("DELETE", "/api/tasks/{task_id}"),
            ("GET", "/api/recipes/"),
            ("POST", "/api/recipes/"),
            ("GET", "/api/recipes/{recipe_id}"),
            ("PUT", "/api/recipes/{recipe_id}"),
            ("DELETE", "/api/recipes/{recipe_id}"),
            ("GET", "/api/recipes/ingredients"),
            ("POST", "/api/recipes/ingredients"),
            ("POST", "/api/recipes/{recipe_id}/ingredients"),
            ("DELETE", "/api/recipes/{recipe_id}/ingredients/{ingredient_id}"),
            ("GET", "/api/recipes/{recipe_id}/availability"),
            ("GET", "/api/inventory"),
            ("POST", "/api/inventory"),
            ("PUT", "/api/inventory/{item_id}"),
            ("DELETE", "/api/inventory/{item_id}"),
            ("GET", "/api/meal-plans"),
            ("POST", "/api/meal-plans"),
            ("DELETE", "/api/meal-plans/{meal_id}"),
            ("GET", "/api/medications/catalog"),
            ("POST", "/api/medications/catalog"),
            ("DELETE", "/api/medications/catalog/{medication_id}"),
            ("GET", "/api/medications/plans"),
            ("POST", "/api/medications/plans"),
            ("DELETE", "/api/medications/plans/{plan_id}"),
            ("GET", "/api/medications/logs"),
            ("POST", "/api/medications/logs"),
            ("GET", "/api/gym/exercises"),
            ("POST", "/api/gym/exercises"),
            ("PUT", "/api/gym/exercises/{exercise_id}"),
            ("DELETE", "/api/gym/exercises/{exercise_id}"),
            ("GET", "/api/gym/sets"),
            ("POST", "/api/gym/sets"),
            ("PUT", "/api/gym/sets/{set_id}"),
            ("DELETE", "/api/gym/sets/{set_id}"),
            ("GET", "/api/gym/history"),
            ("POST", "/api/gym/history"),
            ("DELETE", "/api/gym/history/{history_id}"),
            ("GET", "/api/media/"),
            ("POST", "/api/media/"),
            ("PUT", "/api/media/{media_id}/"),
            ("DELETE", "/api/media/{media_id}/"),
            ("POST", "/api/media/bulk"),
            ("POST", "/api/ai/agent/chat"),
            ("POST", "/api/ai/agent/chat/stream"),
            ("GET", "/api/backups/export/{module}"),
            ("POST", "/api/backups/restore/preview"),
            ("POST", "/api/backups/restore"),
        }
        self.assertEqual(set(), expected - actual)

    def test_schema_validation_rejects_invalid_values(self):
        with self.assertRaises(ValidationError):
            TaskCreate(title="", priority="urgent")
        with self.assertRaises(ValidationError):
            InventoryCreate(name="Rice", quantity=-1, unit="kg")

    def test_domain_enums_are_case_insensitive_at_api_boundary(self):
        self.assertEqual("medium", TaskCreate(title="Call", priority="Medium").priority)
        self.assertEqual("high", TaskUpdate(priority="HIGH").priority)
        self.assertEqual("Medium", RecipeCreate(name="Soup", difficulty="medium").difficulty)
        self.assertEqual("dinner", MealCreate(date="2026-08-31", meal_type="Dinner").meal_type)

        media = MediaCreate(
            title="Dune",
            media_type="TV Show",
            status="Plan-To-Watch",
        )
        self.assertEqual("tv_show", media.media_type)
        self.assertEqual("plan_to_watch", media.status)
        self.assertEqual("on_hold", MediaUpdate(status="On Hold").status)

    def test_boundary_models_forbid_unknown_fields_and_nonpositive_ids(self):
        with self.assertRaises(ValidationError):
            TaskCreate.model_validate({"title": "Write", "titel": "ignored"})
        with self.assertRaises(ValidationError):
            ChatRequest.model_validate({"message": "hello", "prompt": "ignored"})
        with self.assertRaises(ValidationError):
            BulkMedia.model_validate(
                {
                    "items": [
                        {
                            "title": "Dune",
                            "media_type": "book",
                            "unexpected": True,
                        }
                    ]
                }
            )
        with self.assertRaises(ValidationError):
            MedicationPlanCreate(plan_name="Morning", medication_id=0)
        with self.assertRaises(ValidationError):
            MedicationPlanCreate(plan_name="Morning", medication_id=True)
        with self.assertRaises(ValidationError):
            WorkoutExercise(exercise_id=-1)
        with self.assertRaises(ValidationError):
            AIActionRequest(
                request_id="81be4fcc-cee4-4ac7-95dc-f7bf33df99c2",
                action="task.create",
                arguments={"title": "Write"},
                context={"task_id": True},
            )

    def test_media_and_workout_domain_constraints(self):
        media = MediaCreate(
            title="Dune",
            media_type="book",
            release_year=1965,
            progress_current=10,
            progress_total=20,
        )
        self.assertEqual(10, media.progress_current)
        workout = WorkoutCreate(
            session_date="2026-08-25",
            name="  Evening Session  ",
        )
        self.assertEqual("Evening Session", workout.name)
        for model, payload in (
            (MediaCreate, {"title": "Dune", "media_type": "book", "release_year": 999}),
            (MediaCreate, {"title": "Dune", "media_type": "book", "progress_current": -1}),
            (MediaCreate, {"title": "Dune", "media_type": "book", "progress_current": 2, "progress_total": 1}),
            (MediaUpdate, {"progress_current": 2, "progress_total": 1}),
            (WorkoutCreate, {"session_date": "2026-08-25", "name": "   "}),
        ):
            with self.subTest(model=model.__name__, payload=payload):
                with self.assertRaises(ValidationError):
                    model.model_validate(payload)

    def test_external_collections_are_bounded(self):
        schedule_times = [f"{hour:02d}:00" for hour in range(24)]
        self.assertEqual(
            24,
            len(
                MedicationPlanCreate(
                    plan_name="Morning",
                    medication_id=1,
                    schedule_times=schedule_times,
                ).schedule_times
            ),
        )
        self.assertEqual(
            200,
            len(
                TrainingSetCreate(
                    name="Maximum set",
                    exercises=[{"exercise_id": 1}] * 200,
                ).exercises
            ),
        )
        self.assertEqual(100, len(WorkoutExercise(sets=[{}] * 100).sets))
        self.assertEqual(
            500,
            len(
                BulkMedia(
                    items=[
                        {"title": f"Item {index}", "media_type": "book"}
                        for index in range(500)
                    ]
                ).items
            ),
        )

        with self.assertRaises(ValidationError):
            MedicationPlanCreate(
                plan_name="Morning",
                medication_id=1,
                schedule_times=schedule_times + ["23:59"],
            )
        with self.assertRaises(ValidationError):
            TrainingSetCreate(
                name="Too large",
                exercises=[{"exercise_id": 1}] * 201,
            )
        with self.assertRaises(ValidationError):
            WorkoutExercise(sets=[{}] * 101)
        with self.assertRaises(ValidationError):
            BulkMedia(items=[])
        with self.assertRaises(ValidationError):
            BulkMedia(
                items=[
                    {"title": f"Item {index}", "media_type": "book"}
                    for index in range(501)
                ]
            )

    def test_frontend_proxies_block_internal_api_routes(self):
        vite = (ROOT / "frontend" / "vite.config.ts").read_text()
        nginx = (ROOT / "frontend" / "nginx.conf").read_text()
        self.assertIn('path.startsWith("/api/internal/")', vite)
        self.assertIn('path === "/api/internal"', vite)
        self.assertIn("configurePreviewServer", vite)
        self.assertIn('"http://localhost:8001"', vite)
        self.assertLess(
            vite.index("plugins: [blockInternalApi"),
            vite.index('proxy: {\n      "/api"'),
        )
        self.assertIn("location = /api/internal", nginx)
        self.assertIn("location /api/internal/", nginx)
        self.assertIn("location = /api/ai/agent/chat/stream", nginx)
        self.assertIn("proxy_buffering off", nginx)
        self.assertLess(
            nginx.index("location = /api/internal"),
            nginx.index("location /api/"),
        )
        self.assertIn("client_max_body_size 250m", nginx)

    def test_public_path_identifiers_are_positive(self):
        for path, operations in app.openapi()["paths"].items():
            if "{" not in path:
                continue
            for operation in operations.values():
                if not isinstance(operation, dict):
                    continue
                for parameter in operation.get("parameters", []):
                    if (
                        parameter.get("in") == "path"
                        and parameter["name"].endswith("id")
                        and parameter["schema"].get("type") == "integer"
                    ):
                        self.assertEqual(
                            0,
                            parameter["schema"].get("exclusiveMinimum"),
                            f"{path} {parameter['name']}",
                        )

    def test_ai_actions_are_allowlisted(self):
        with self.assertRaises(ValidationError):
            AIActionRequest(
                request_id="81be4fcc-cee4-4ac7-95dc-f7bf33df99c2",
                action="sql.execute",
                arguments={"sql": "DROP TABLE tasks"},
            )
        for action in AI_WRITE_ACTIONS:
            AIActionRequest(
                request_id="81be4fcc-cee4-4ac7-95dc-f7bf33df99c2",
                action=action,
                arguments={},
            )

    def test_numeric_response_helpers_preserve_exact_decimal_text(self):
        exact = Decimal("12345678.91")
        exact_weight = Decimal("123456.79")
        inventory = kitchen._decimal_fields(
            {"quantity": exact, "min_quantity": exact},
            "quantity",
            "min_quantity",
        )
        workout = gym._workout_exercise({"weight_kg": exact_weight})
        self.assertEqual(str(exact), inventory["quantity"])
        self.assertEqual(str(exact), inventory["min_quantity"])
        self.assertEqual(str(exact_weight), workout["weight_kg"])

    def test_backup_snapshot_only_accepts_its_known_module_tables_and_columns(self):
        snapshot = {
            "format": backups.BACKUP_FORMAT,
            "version": backups.BACKUP_VERSION,
            "module": "tasks",
            "tables": {
                "tasks": [{
                    "id": 1, "title": "Backup", "description": None,
                    "priority": "medium", "completed": False, "due_date": None,
                    "created_at": "2026-08-19T00:00:00+00:00",
                    "updated_at": "2026-08-19T00:00:00+00:00",
                    "completion_date": None,
                }],
            },
        }
        parsed = backups._parse_snapshot(json.dumps({"snapshot": snapshot}).encode())
        self.assertEqual("tasks", parsed["module"])
        snapshot["tables"]["ai_entity_embeddings"] = []
        with self.assertRaises(Exception):
            backups._parse_snapshot(json.dumps({"snapshot": snapshot}).encode())


class AIHealthProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_downstream_unhealthy_status(self):
        downstream = MagicMock()
        downstream.status_code = 503
        downstream.json.return_value = {
            "status": "degraded",
            "models_available": False,
        }
        client = MagicMock()
        client.get = AsyncMock(return_value=downstream)
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=False)

        with patch.object(ai_router.httpx, "AsyncClient", return_value=manager):
            response = await ai_router.ai_health()

        self.assertEqual(503, response.status_code)
        self.assertEqual(
            {"status": "degraded", "models_available": False},
            json.loads(response.body),
        )

    async def test_returns_unhealthy_status_when_ai_service_is_unreachable(self):
        client = MagicMock()
        client.get = AsyncMock(
            side_effect=ai_router.httpx.ConnectError("connection refused")
        )
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=client)
        manager.__aexit__ = AsyncMock(return_value=False)

        with patch.object(ai_router.httpx, "AsyncClient", return_value=manager):
            response = await ai_router.ai_health()

        self.assertEqual(503, response.status_code)
        self.assertEqual("degraded", json.loads(response.body)["status"])


class PublicPathBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_nonpositive_identifiers_are_rejected_at_the_asgi_boundary(self):
        requests = (
            ("GET", "/api/tasks/0"),
            ("DELETE", "/api/tasks/-1"),
            ("GET", "/api/recipes/0"),
            ("DELETE", "/api/inventory/-1"),
            ("DELETE", "/api/medications/catalog/0"),
            ("PUT", "/api/gym/exercises/0"),
            ("DELETE", "/api/gym/exercises/-1"),
            ("DELETE", "/api/media/0/"),
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            for method, path in requests:
                with self.subTest(method=method, path=path):
                    response = await client.request(method, path)
                    self.assertEqual(401, response.status_code)


class DatabaseReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_readiness_requires_the_expected_migration_revision(self):
        conn = MagicMock()
        conn.fetchval = AsyncMock(return_value=True)
        manager = MagicMock()
        manager.__aenter__ = AsyncMock(return_value=conn)
        manager.__aexit__ = AsyncMock(return_value=False)

        with patch.object(api_db, "connection", return_value=manager):
            self.assertTrue(await api_db.ready())

        sql, revision = conn.fetchval.await_args.args
        self.assertIn("alembic_version", sql)
        self.assertEqual(api_db.EXPECTED_ALEMBIC_REVISION, revision)


if __name__ == "__main__":
    unittest.main()
