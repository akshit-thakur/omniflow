from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from ..db import connection
from ..schemas import (
    TaskCreate,
    TaskUpdate,
)

router = APIRouter()
PositivePath = Annotated[int, Path(gt=0)]

TASK_COLUMNS = """
id, title, description, priority, completed, due_date,
created_at, updated_at, completion_date
"""
@router.get("/tasks/")
async def list_tasks():
    async with connection() as conn:
        rows = await conn.fetch(f"SELECT {TASK_COLUMNS} FROM tasks ORDER BY completed, created_at DESC")
    return [dict(row) for row in rows]


@router.post("/tasks/", status_code=status.HTTP_201_CREATED)
async def create_task(body: TaskCreate):
    async with connection() as conn:
        row = await conn.fetchrow(
            f"""INSERT INTO tasks(title, description, priority, due_date)
                VALUES($1, $2, $3, $4) RETURNING {TASK_COLUMNS}""",
            body.title, body.description, body.priority, body.due_date,
        )
    return dict(row)


@router.get("/tasks/{task_id}")
async def get_task(task_id: PositivePath):
    async with connection() as conn:
        row = await conn.fetchrow(f"SELECT {TASK_COLUMNS} FROM tasks WHERE id=$1", task_id)
    if not row:
        raise HTTPException(404, "Task not found")
    return dict(row)


@router.put("/tasks/{task_id}")
async def update_task(task_id: PositivePath, body: TaskUpdate):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return await get_task(task_id)
    if "completed" in changes:
        changes["completion_date"] = "CURRENT_TIMESTAMP" if changes["completed"] else None

    assignments: list[str] = []
    values: list[object] = []
    for key, value in changes.items():
        if key == "completion_date" and value == "CURRENT_TIMESTAMP":
            assignments.append("completion_date = CURRENT_TIMESTAMP")
        else:
            values.append(value)
            assignments.append(f"{key} = ${len(values)}")
    values.append(task_id)
    async with connection() as conn:
        row = await conn.fetchrow(
            f"UPDATE tasks SET {', '.join(assignments)} WHERE id=${len(values)} RETURNING {TASK_COLUMNS}",
            *values,
        )
    if not row:
        raise HTTPException(404, "Task not found")
    return dict(row)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: PositivePath):
    async with connection() as conn:
        deleted = await conn.fetchval("DELETE FROM tasks WHERE id=$1 RETURNING id", task_id)
    if not deleted:
        raise HTTPException(404, "Task not found")
    return {"message": "Task deleted successfully"}
