from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from ..db import connection
from ..schemas import ExerciseCreate, TrainingSetCreate, WorkoutCreate

router = APIRouter(prefix="/gym")
PositivePath = Annotated[int, Path(gt=0)]


def _workout_exercise(row) -> dict:
    result = dict(row)
    if result.get("weight_kg") is not None:
        value = result["weight_kg"]
        result["weight_kg"] = format(value, "f") if isinstance(value, Decimal) else str(value)
    return result


@router.get("/exercises")
async def list_exercises():
    async with connection() as conn:
        rows = await conn.fetch(
            "SELECT id,name,muscle_group,equipment,description FROM exercise_catalog ORDER BY name"
        )
    return [dict(row) for row in rows]


@router.post("/exercises", status_code=status.HTTP_201_CREATED)
async def create_exercise(body: ExerciseCreate):
    async with connection() as conn:
        row = await conn.fetchrow(
            """INSERT INTO exercise_catalog(name,muscle_group,equipment,description)
               VALUES($1,$2,$3,$4) RETURNING id,name,muscle_group,equipment,description""",
            body.name, body.muscle_group, body.equipment, body.description,
        )
    return dict(row)

@router.put("/exercises/{exercise_id}")
async def update_exercise(exercise_id: PositivePath, body: ExerciseCreate):
    async with connection() as conn:
        row = await conn.fetchrow(
            """UPDATE exercise_catalog
               SET name=$2,muscle_group=$3,equipment=$4,description=$5
               WHERE id=$1
               RETURNING id,name,muscle_group,equipment,description""",
            exercise_id, body.name, body.muscle_group, body.equipment, body.description,
        )
    if not row:
        raise HTTPException(404, "Exercise not found")
    return dict(row)


@router.delete("/exercises/{exercise_id}")
async def delete_exercise(exercise_id: PositivePath):
    async with connection() as conn:
        deleted = await conn.fetchval("DELETE FROM exercise_catalog WHERE id=$1 RETURNING id", exercise_id)
    if not deleted:
        raise HTTPException(404, "Exercise not found")
    return {"message": "Exercise deleted"}


async def _training_set(conn, set_id: int):
    row = await conn.fetchrow(
        "SELECT id,name,description FROM training_sets WHERE id=$1",
        set_id,
    )
    if not row:
        return None
    exercises = await conn.fetch(
        """SELECT tse.id,tse.exercise_id,e.name AS exercise_name,tse.order_index
           FROM training_set_exercises tse JOIN exercise_catalog e ON e.id=tse.exercise_id
           WHERE tse.training_set_id=$1 ORDER BY tse.order_index""",
        set_id,
    )
    result = dict(row)
    result["exercises"] = [dict(item) for item in exercises]
    return result


@router.get("/sets")
async def list_training_sets():
    async with connection() as conn:
        ids = await conn.fetch("SELECT id FROM training_sets ORDER BY name")
        return [await _training_set(conn, row["id"]) for row in ids]


@router.post("/sets", status_code=status.HTTP_201_CREATED)
async def create_training_set(body: TrainingSetCreate):
    async with connection() as conn:
        async with conn.transaction():
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
            result = await _training_set(conn, set_id)
    return result



@router.put("/sets/{set_id}")
async def update_training_set(set_id: PositivePath, body: TrainingSetCreate):
    async with connection() as conn:
        async with conn.transaction():
            updated = await conn.fetchval(
                """UPDATE training_sets SET name=$2,description=$3
                   WHERE id=$1 RETURNING id""",
                set_id, body.name, body.description,
            )
            if not updated:
                raise HTTPException(404, "Training set not found")
            await conn.execute(
                "DELETE FROM training_set_exercises WHERE training_set_id=$1",
                set_id,
            )
            if body.exercises:
                await conn.executemany(
                    """INSERT INTO training_set_exercises(training_set_id,exercise_id,order_index)
                       VALUES($1,$2,$3)""",
                    [(set_id, item.exercise_id, index) for index, item in enumerate(body.exercises)],
                )
            result = await _training_set(conn, set_id)
    return result
@router.delete("/sets/{set_id}")
async def delete_training_set(set_id: PositivePath):
    async with connection() as conn:
        deleted = await conn.fetchval("DELETE FROM training_sets WHERE id=$1 RETURNING id", set_id)
    if not deleted:
        raise HTTPException(404, "Training set not found")
    return {"message": "Training set deleted"}


async def _workout(conn, workout_id: int):
    row = await conn.fetchrow(
        """SELECT ws.id,ws.training_set_id,ws.set_name,ws.session_date,
                  ws.duration_minutes,ws.notes
           FROM workout_sessions ws WHERE ws.id=$1""",
        workout_id,
    )
    if not row:
        return None
    exercises = await conn.fetch(
        """SELECT id,exercise_name,sets_completed,reps_completed,weight_kg,details AS sets
           FROM workout_session_exercises WHERE workout_session_id=$1 ORDER BY id""",
        workout_id,
    )
    result = dict(row)
    result["exercises"] = [_workout_exercise(item) for item in exercises]
    return result


@router.get("/history")
async def list_history():
    async with connection() as conn:
        ids = await conn.fetch("SELECT id FROM workout_sessions ORDER BY session_date DESC,created_at DESC")
        return [await _workout(conn, row["id"]) for row in ids]


@router.post("/history", status_code=status.HTTP_201_CREATED)
async def create_history(body: WorkoutCreate):
    async with connection() as conn:
        async with conn.transaction():
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
                    exercise_name = await conn.fetchval(
                        "SELECT name FROM exercise_catalog WHERE id=$1", item.exercise_id
                    )
                if not exercise_name:
                    raise HTTPException(422, "Each workout exercise needs a valid exercise")
                sets_completed = (
                    item.sets_completed
                    if "sets_completed" in item.model_fields_set
                    else len(item.sets)
                )
                await conn.execute(
                    """INSERT INTO workout_session_exercises(
                         workout_session_id,exercise_id,exercise_name,sets_completed,
                         reps_completed,weight_kg,details
                       ) VALUES($1,$2,$3,$4,$5,$6,$7::jsonb)""",
                    workout_id, item.exercise_id, exercise_name, sets_completed,
                    item.reps_completed, item.weight_kg,
                    __import__("json").dumps(item.sets),
                )
            result = await _workout(conn, workout_id)
    return result


@router.delete("/history/{history_id}")
async def delete_history(history_id: PositivePath):
    async with connection() as conn:
        deleted = await conn.fetchval("DELETE FROM workout_sessions WHERE id=$1 RETURNING id", history_id)
    if not deleted:
        raise HTTPException(404, "Workout history not found")
    return {"message": "Workout history deleted"}
