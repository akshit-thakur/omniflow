import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .db import connection
from .ollama import runtime
from .settings import get_settings

logger = logging.getLogger(__name__)

_index_sync_lock = asyncio.Lock()
_index_sync_state: dict[str, Any] = {}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def reset_index_sync_state(*, enabled: bool) -> None:
    """Reset process-local readiness state when the service lifespan starts."""
    global _index_sync_state
    _index_sync_state = {
        "enabled": enabled,
        "in_progress": False,
        "attempt_count": 0,
        "successful_once": False,
        "last_attempt_started_at": None,
        "last_completed_at": None,
        "last_attempt_succeeded": None,
        "last_success_at": None,
        "last_error": None,
    }


def index_sync_status() -> dict[str, Any]:
    return dict(_index_sync_state)


reset_index_sync_state(enabled=False)


SOURCE_QUERIES: dict[str, str] = {
    "tasks": """
        SELECT id::text AS entity_id,
               concat_ws(' ', 'Task', title, description, 'priority', priority,
                         CASE WHEN completed THEN 'completed' ELSE 'pending' END,
                         due_date::text) AS content,
               jsonb_build_object('id',id,'title',title,'description',description,
                 'priority',priority,'completed',completed,'due_date',due_date)::text AS metadata
        FROM tasks
    """,
    "medications": """
        SELECT id::text AS entity_id,
               concat_ws(' ', 'Medication',name,common_dosage,notes) AS content,
               jsonb_build_object('id',id,'name',name,'common_dosage',common_dosage,
                 'notes',notes)::text AS metadata
        FROM medications
    """,
    "medication_plans": """
        SELECT mp.id::text AS entity_id,
               concat_ws(' ', 'Medication plan',mp.plan_name,m.name,mp.dosage,mp.notes,
                         CASE WHEN mp.active THEN 'active' ELSE 'inactive' END) AS content,
               jsonb_build_object('id',mp.id,'plan_name',mp.plan_name,'medication_id',
                 mp.medication_id,'medication_name',m.name,'dosage',mp.dosage,
                 'active',mp.active)::text AS metadata
        FROM medication_plans mp JOIN medications m ON m.id=mp.medication_id
    """,
    "medication_logs": """
        SELECT ml.id::text AS entity_id,
               concat_ws(' ', 'Medication log',m.name,mp.plan_name,ml.taken_at::text,
                         ml.scheduled_time::text,ml.notes) AS content,
               jsonb_build_object('id',ml.id,'plan_id',ml.plan_id,'plan_name',mp.plan_name,
                 'medication_id',mp.medication_id,'medication_name',m.name,
                 'taken_at',ml.taken_at,'scheduled_time',ml.scheduled_time,
                 'notes',ml.notes)::text AS metadata
        FROM medication_logs ml
        JOIN medication_plans mp ON mp.id=ml.plan_id
        JOIN medications m ON m.id=mp.medication_id
    """,
    "exercises": """
        SELECT id::text AS entity_id,
               concat_ws(' ', 'Exercise',name,muscle_group,equipment,description) AS content,
               jsonb_build_object('id',id,'name',name,'muscle_group',muscle_group,
                 'equipment',equipment,'description',description)::text AS metadata
        FROM exercise_catalog
    """,
    "training_sets": """
        SELECT ts.id::text AS entity_id,
               concat_ws(' ', 'Training set',ts.name,ts.description,
                         string_agg(e.name,' ')) AS content,
               jsonb_build_object('id',ts.id,'name',ts.name,'description',ts.description)::text AS metadata
        FROM training_sets ts
        LEFT JOIN training_set_exercises tse ON tse.training_set_id=ts.id
        LEFT JOIN exercise_catalog e ON e.id=tse.exercise_id
        GROUP BY ts.id
    """,
    "ingredients": """
        SELECT id::text AS entity_id,
               concat_ws(' ', 'Ingredient',name,category,default_unit) AS content,
               jsonb_build_object('id',id,'name',name,'category',category,
                 'default_unit',default_unit)::text AS metadata
        FROM ingredients
    """,
    "workouts": """
        SELECT ws.id::text AS entity_id,
               concat_ws(' ', 'Workout',ws.set_name,ws.session_date::text,ws.notes,
                         string_agg(wse.exercise_name,' ')) AS content,
               jsonb_build_object('id',ws.id,'training_set_id',ws.training_set_id,
                 'set_name',ws.set_name,'session_date',ws.session_date,
                 'duration_minutes',ws.duration_minutes,'notes',ws.notes)::text AS metadata
        FROM workout_sessions ws
        LEFT JOIN workout_session_exercises wse ON wse.workout_session_id=ws.id
        GROUP BY ws.id
    """,
    "recipes": """
        SELECT r.id::text AS entity_id,
               concat_ws(' ', 'Recipe',r.name,r.description,r.instructions,r.difficulty,
                         string_agg(i.name,' ')) AS content,
               jsonb_build_object('id',r.id,'name',r.name,'description',r.description,
                 'difficulty',r.difficulty,'prep_time_minutes',r.prep_time_minutes)::text AS metadata
        FROM recipes r
        LEFT JOIN recipe_ingredients ri ON ri.recipe_id=r.id
        LEFT JOIN ingredients i ON i.id=ri.ingredient_id
        GROUP BY r.id
    """,
    "inventory": """
        SELECT inv.id::text AS entity_id,
               concat_ws(' ', 'Inventory',i.name,inv.quantity::text,inv.unit,i.category,
                         inv.expiry_date::text) AS content,
               jsonb_build_object('id',inv.id,'name',i.name,'quantity',inv.quantity,
                 'unit',inv.unit,'category',i.category,'expiry_date',inv.expiry_date,
                 'min_quantity',inv.min_quantity)::text AS metadata
        FROM inventory inv JOIN ingredients i ON i.id=inv.ingredient_id
    """,
    "meals": """
        SELECT me.id::text AS entity_id,
               concat_ws(' ', 'Meal',me.meal_date::text,me.meal_type,r.name,me.notes) AS content,
               jsonb_build_object('id',me.id,'date',me.meal_date,'meal_type',me.meal_type,
                 'recipe_id',me.recipe_id,'recipe_name',r.name,'notes',me.notes)::text AS metadata
        FROM meal_entries me LEFT JOIN recipes r ON r.id=me.recipe_id
    """,
    "media": """
        SELECT id::text AS entity_id,
               concat_ws(' ', 'Media',title,media_type,status,author_creator,release_year::text,
                         genre,notes,review) AS content,
               jsonb_build_object('id',id,'title',title,'media_type',media_type,'status',status,
                 'author_creator',author_creator,'release_year',release_year,'genre',genre,
                 'progress_current',progress_current,'progress_total',progress_total,
                 'is_favorite',is_favorite,'rating',rating)::text AS metadata
        FROM media_items
    """,
}


def _hash(text: str, metadata: str | dict[str, Any]) -> str:
    """Hash every indexed field so metadata-only changes trigger re-embedding."""
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata, parse_float=Decimal)
        except json.JSONDecodeError:
            pass
    document = json.dumps(
        {"text": text, "metadata": metadata},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(document.encode("utf-8")).hexdigest()


async def reindex() -> dict[str, Any]:
    settings = get_settings()
    indexed = unchanged = deleted = 0
    async with connection() as conn:
        known_sources = list(SOURCE_QUERIES)
        result = await conn.execute(
            """DELETE FROM ai_entity_embeddings
               WHERE NOT(entity_table=ANY($1::text[]))""",
            known_sources,
        )
        deleted += int(result.split()[-1])
        for source, query in SOURCE_QUERIES.items():
            source_rows = await conn.fetch(query)
            current = {
                row["entity_id"]: (
                    row["index_version"],
                    row["content_hash"],
                    row["has_embedding"],
                )
                for row in await conn.fetch(
                    """SELECT entity_id,index_version,content_hash,
                              embedding IS NOT NULL AS has_embedding
                       FROM ai_entity_embeddings
                       WHERE entity_table=$1 AND embedding_model=$2""",
                    source,
                    settings.embedding_model,
                )
            }

            async def write_batch(batch: list[dict[str, Any]]) -> None:
                nonlocal indexed
                if not batch:
                    return
                vectors = await runtime.embeddings([item["text"] for item in batch])
                upsert_sql = """
                    INSERT INTO ai_entity_embeddings(
                      entity_table,entity_id,content,metadata,embedding,
                      embedding_model,index_version,content_hash,updated_at
                    ) VALUES($1,$2,$3,$4::jsonb,$5::vector,$6,$7,$8,CURRENT_TIMESTAMP)
                    ON CONFLICT(entity_table,entity_id,embedding_model) DO UPDATE SET
                      content=EXCLUDED.content,metadata=EXCLUDED.metadata,
                      embedding=EXCLUDED.embedding,embedding_model=EXCLUDED.embedding_model,
                      index_version=EXCLUDED.index_version,content_hash=EXCLUDED.content_hash,
                      updated_at=CURRENT_TIMESTAMP
                """
                arguments = [
                    (
                        source,
                        item["entity_id"],
                        item["text"],
                        item["metadata"],
                        json.dumps(vector),
                        settings.embedding_model,
                        settings.index_version,
                        item["hash"],
                    )
                    for item, vector in zip(batch, vectors, strict=True)
                ]
                async with conn.transaction():
                    if len(arguments) == 1:
                        await conn.execute(upsert_sql, *arguments[0])
                    else:
                        await conn.executemany(upsert_sql, arguments)
                indexed += len(batch)

            batch: list[dict[str, Any]] = []
            live_ids = []
            for row in source_rows:
                entity_id = row["entity_id"]
                live_ids.append(entity_id)
                item = {
                    "entity_id": entity_id,
                    "text": row["content"],
                    "metadata": row["metadata"],
                    "hash": _hash(row["content"], row["metadata"]),
                }
                if current.get(entity_id) == (settings.index_version, item["hash"], True):
                    unchanged += 1
                    continue
                batch.append(item)
                if len(batch) == 32:
                    await write_batch(batch)
                    batch.clear()
            await write_batch(batch)

            if live_ids:
                result = await conn.execute(
                    """DELETE FROM ai_entity_embeddings
                       WHERE entity_table=$1 AND (
                         embedding_model IS DISTINCT FROM $2
                         OR index_version IS DISTINCT FROM $3
                         OR NOT(entity_id=ANY($4::text[]))
                       )""",
                    source,
                    settings.embedding_model,
                    settings.index_version,
                    live_ids,
                )
            else:
                result = await conn.execute(
                    "DELETE FROM ai_entity_embeddings WHERE entity_table=$1", source
                )
            deleted += int(result.split()[-1])
    return {"indexed": indexed, "unchanged": unchanged, "deleted": deleted}


async def index_status() -> dict[str, Any]:
    settings = get_settings()
    async with connection() as conn:
        row = await conn.fetchrow(
            """SELECT count(*) AS total,
                      count(*) FILTER(
                        WHERE embedding_model IS DISTINCT FROM $1
                           OR index_version IS DISTINCT FROM $2
                           OR embedding IS NULL
                           OR NOT(entity_table=ANY($3::text[]))
                      ) AS stale,
                      max(updated_at) AS last_updated_at
               FROM ai_entity_embeddings""",
            settings.embedding_model,
            settings.index_version,
            list(SOURCE_QUERIES),
        )
    return {
        "total": row["total"],
        "stale": row["stale"],
        "last_updated_at": (
            row["last_updated_at"].isoformat() if row["last_updated_at"] else None
        ),
        "embedding_model": settings.embedding_model,
        "index_version": settings.index_version,
    }


async def synchronize_index() -> dict[str, Any]:
    """Run one serialized index sync and retain its readiness outcome."""
    async with _index_sync_lock:
        _index_sync_state["in_progress"] = True
        _index_sync_state["attempt_count"] += 1
        _index_sync_state["last_attempt_started_at"] = _timestamp()
        try:
            result = await reindex()
        except asyncio.CancelledError:
            _index_sync_state["last_completed_at"] = _timestamp()
            _index_sync_state["last_attempt_succeeded"] = False
            _index_sync_state["last_error"] = "Index synchronization was cancelled"
            raise
        except Exception as exc:
            _index_sync_state["last_completed_at"] = _timestamp()
            _index_sync_state["last_attempt_succeeded"] = False
            _index_sync_state["last_error"] = str(exc) or type(exc).__name__
            raise
        else:
            completed_at = _timestamp()
            _index_sync_state["successful_once"] = True
            _index_sync_state["last_completed_at"] = completed_at
            _index_sync_state["last_attempt_succeeded"] = True
            _index_sync_state["last_success_at"] = completed_at
            _index_sync_state["last_error"] = None
            return result
        finally:
            _index_sync_state["in_progress"] = False


async def sync_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            result = await synchronize_index()
            logger.info("Index synchronization complete: %s", result)
        except Exception:
            logger.exception("Index synchronization failed")
        try:
            await asyncio.wait_for(stop.wait(), timeout=get_settings().sync_interval_seconds)
        except TimeoutError:
            pass
