from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from ..db import connection
from ..mutations import (
    _apply_media_status_transition,
    _media_completion_for_create,
    _validate_media_progress_state,
)
from ..schemas import BulkMedia, MediaCreate, MediaUpdate

router = APIRouter(prefix="/media")

MEDIA_COLS = """
id,title,media_type,status,author_creator,release_year,genre,progress_current,
progress_total,is_favorite,rating,notes,review,completion_date,created_at,updated_at
"""


@router.get("/")
async def list_media():
    async with connection() as conn:
        rows = await conn.fetch(f"SELECT {MEDIA_COLS} FROM media_items ORDER BY created_at DESC")
    return [dict(row) for row in rows]


async def _insert_media(conn, body: MediaCreate):
    completion_date = _media_completion_for_create(body.status)
    return await conn.fetchrow(
        f"""INSERT INTO media_items(
              title,media_type,status,author_creator,release_year,genre,
              progress_current,progress_total,is_favorite,notes,completion_date
            ) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) RETURNING {MEDIA_COLS}""",
        body.title, body.media_type, body.status, body.author_creator, body.release_year,
        body.genre, body.progress_current, body.progress_total, body.is_favorite, body.notes,
        completion_date,
    )


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_media(body: MediaCreate):
    async with connection() as conn:
        row = await _insert_media(conn, body)
    return dict(row)


@router.post("/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_media(body: BulkMedia):
    async with connection() as conn:
        async with conn.transaction():
            rows = [dict(await _insert_media(conn, item)) for item in body.items]
    return {"items": rows, "created": len(rows)}


@router.put("/{media_id}/")
async def update_media(media_id: Annotated[int, Path(gt=0)], body: MediaUpdate):
    changes = body.model_dump(exclude_unset=True)
    async with connection() as conn:
        if not changes:
            row = await conn.fetchrow(f"SELECT {MEDIA_COLS} FROM media_items WHERE id=$1", media_id)
        else:
            async with conn.transaction():
                before = await conn.fetchrow(
                    f"SELECT {MEDIA_COLS} FROM media_items WHERE id=$1 FOR UPDATE",
                    media_id,
                )
                if not before:
                    raise HTTPException(404, "Media item not found")
                _validate_media_progress_state(changes, dict(before))
                _apply_media_status_transition(changes, dict(before))
                values = list(changes.values()) + [media_id]
                assignments = [f"{key}=${i}" for i, key in enumerate(changes, 1)]
                row = await conn.fetchrow(
                    f"UPDATE media_items SET {','.join(assignments)} WHERE id=${len(values)} RETURNING {MEDIA_COLS}",
                    *values,
                )
    if not row:
        raise HTTPException(404, "Media item not found")
    return dict(row)


@router.delete("/{media_id}/")
async def delete_media(media_id: Annotated[int, Path(gt=0)]):
    async with connection() as conn:
        deleted = await conn.fetchval("DELETE FROM media_items WHERE id=$1 RETURNING id", media_id)
    if not deleted:
        raise HTTPException(404, "Media item not found")
    return {"message": "Media item deleted"}
