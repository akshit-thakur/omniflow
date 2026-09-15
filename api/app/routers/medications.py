from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from ..db import connection
from ..schemas import MedicationCreate, MedicationLogCreate, MedicationPlanCreate

router = APIRouter(prefix="/medications")
PositivePath = Annotated[int, Path(gt=0)]


@router.get("/catalog")
async def list_medications():
    async with connection() as conn:
        rows = await conn.fetch(
            "SELECT id,name,common_dosage,notes,created_at FROM medications ORDER BY name"
        )
    return [dict(row) for row in rows]


@router.post("/catalog", status_code=status.HTTP_201_CREATED)
async def create_medication(body: MedicationCreate):
    async with connection() as conn:
        row = await conn.fetchrow(
            """INSERT INTO medications(name,common_dosage,notes) VALUES($1,$2,$3)
               RETURNING id,name,common_dosage,notes,created_at""",
            body.name, body.common_dosage, body.notes,
        )
    return dict(row)


@router.delete("/catalog/{medication_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_medication(medication_id: PositivePath):
    async with connection() as conn:
        deleted = await conn.fetchval("DELETE FROM medications WHERE id=$1 RETURNING id", medication_id)
    if not deleted:
        raise HTTPException(404, "Medication not found")


PLAN_SELECT = """
SELECT mp.id, mp.plan_name, mp.medication_id, m.name AS medication_name,
       mp.dosage, mp.notes, mp.active, mp.created_at,
       COALESCE(
          array_agg(to_char(mpt.schedule_time,'HH24:MI') ORDER BY mpt.schedule_time)
          FILTER (WHERE mpt.id IS NOT NULL), ARRAY[]::text[]
       ) AS schedule_times
FROM medication_plans mp
JOIN medications m ON m.id=mp.medication_id
LEFT JOIN medication_plan_times mpt ON mpt.plan_id=mp.id
"""


@router.get("/plans")
async def list_plans():
    async with connection() as conn:
        rows = await conn.fetch(
            f"{PLAN_SELECT} GROUP BY mp.id,m.name ORDER BY mp.active DESC,mp.plan_name"
        )
    return [dict(row) for row in rows]


@router.post("/plans", status_code=status.HTTP_201_CREATED)
async def create_plan(body: MedicationPlanCreate):
    async with connection() as conn:
        async with conn.transaction():
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
                f"{PLAN_SELECT} WHERE mp.id=$1 GROUP BY mp.id,m.name",
                plan_id,
            )
    return dict(row)


@router.delete("/plans/{plan_id}")
async def delete_plan(plan_id: PositivePath):
    async with connection() as conn:
        deleted = await conn.fetchval("DELETE FROM medication_plans WHERE id=$1 RETURNING id", plan_id)
    if not deleted:
        raise HTTPException(404, "Medication plan not found")
    return {"message": "Medication plan deleted"}


@router.get("/logs")
async def list_logs():
    async with connection() as conn:
        rows = await conn.fetch(
            """SELECT ml.id,ml.plan_id,mp.plan_name,m.name AS medication_name,mp.dosage,
                      ml.taken_at,to_char(ml.scheduled_time,'HH24:MI') AS scheduled_time,
                      ml.notes,ml.created_at
               FROM medication_logs ml
               JOIN medication_plans mp ON mp.id=ml.plan_id
               JOIN medications m ON m.id=mp.medication_id
               ORDER BY ml.taken_at DESC LIMIT 500"""
        )
    return [dict(row) for row in rows]


@router.post("/logs", status_code=status.HTTP_201_CREATED)
async def create_log(body: MedicationLogCreate):
    async with connection() as conn:
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
    return dict(row)
