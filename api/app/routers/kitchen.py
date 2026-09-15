from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from ..db import connection
from ..schemas import (
    IngredientCreate,
    InventoryCreate,
    InventoryUpdate,
    MealCreate,
    MealBatchRequest,
    MealUpdate,
    RecipeCreate,
    RecipeIngredientAdd,
    RecipeUpdate,
)

router = APIRouter()
PositivePath = Annotated[int, Path(gt=0)]

RECIPE_COLS = "id, name, description, instructions, difficulty, prep_time_minutes, created_at"
INVENTORY_SELECT = """
SELECT inv.id, ing.name, inv.quantity, inv.unit, ing.category, inv.expiry_date,
       inv.min_quantity, inv.quantity <= inv.min_quantity AS is_low_stock,
       (inv.expiry_date IS NOT NULL AND CURRENT_DATE >= inv.created_at::date + CEIL((inv.expiry_date - inv.created_at::date) * 0.9)::int) AS is_expiring_soon
FROM inventory inv JOIN ingredients ing ON ing.id=inv.ingredient_id
"""


def _decimal_fields(row, *fields: str) -> dict:
    result = dict(row)
    for field in fields:
        if result.get(field) is not None:
            value = result[field]
            result[field] = format(value, "f") if isinstance(value, Decimal) else str(value)
    return result


@router.get("/recipes/")
async def list_recipes():
    async with connection() as conn:
        rows = await conn.fetch(
            f"""SELECT {RECIPE_COLS},
                       (SELECT count(*) FROM recipe_ingredients ri WHERE ri.recipe_id=recipes.id) AS ingredient_count
                FROM recipes ORDER BY created_at DESC"""
        )
    return [dict(row) for row in rows]


@router.post("/recipes/", status_code=status.HTTP_201_CREATED)
async def create_recipe(body: RecipeCreate):
    async with connection() as conn:
        row = await conn.fetchrow(
            f"""INSERT INTO recipes(name,description,instructions,difficulty,prep_time_minutes)
                VALUES($1,$2,$3,$4,$5) RETURNING {RECIPE_COLS}""",
            body.name, body.description, body.instructions, body.difficulty, body.prep_time_minutes,
        )
    return dict(row)


@router.get("/recipes/ingredients")
async def list_ingredients():
    async with connection() as conn:
        rows = await conn.fetch("SELECT id,name,category,default_unit FROM ingredients ORDER BY name")
    return [dict(row) for row in rows]


@router.post("/recipes/ingredients", status_code=status.HTTP_201_CREATED)
async def create_ingredient(body: IngredientCreate):
    async with connection() as conn:
        row = await conn.fetchrow(
            """INSERT INTO ingredients(name,category,default_unit) VALUES($1,$2,$3)
               RETURNING id,name,category,default_unit""",
            body.name, body.category, body.default_unit,
        )
    return dict(row)


@router.get("/recipes/{recipe_id}")
async def get_recipe(recipe_id: PositivePath):
    async with connection() as conn:
        row = await conn.fetchrow(f"SELECT {RECIPE_COLS} FROM recipes WHERE id=$1", recipe_id)
        if not row:
            raise HTTPException(404, "Recipe not found")
        ingredients = await conn.fetch(
            """SELECT ri.ingredient_id, i.name AS ingredient_name, ri.quantity, ri.unit
               FROM recipe_ingredients ri JOIN ingredients i ON i.id=ri.ingredient_id
               WHERE ri.recipe_id=$1 ORDER BY i.name""",
            recipe_id,
        )
    result = dict(row)
    result["ingredients"] = [_decimal_fields(item, "quantity") for item in ingredients]
    return result


@router.put("/recipes/{recipe_id}")
async def update_recipe(recipe_id: PositivePath, body: RecipeUpdate):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return await get_recipe(recipe_id)
    values = list(changes.values()) + [recipe_id]
    assignments = [f"{key}=${i}" for i, key in enumerate(changes, 1)]
    async with connection() as conn:
        row = await conn.fetchrow(
            f"UPDATE recipes SET {','.join(assignments)} WHERE id=${len(values)} RETURNING {RECIPE_COLS}",
            *values,
        )
    if not row:
        raise HTTPException(404, "Recipe not found")
    return dict(row)


@router.delete("/recipes/{recipe_id}")
async def delete_recipe(recipe_id: PositivePath):
    async with connection() as conn:
        deleted = await conn.fetchval("DELETE FROM recipes WHERE id=$1 RETURNING id", recipe_id)
    if not deleted:
        raise HTTPException(404, "Recipe not found")
    return {"message": "Recipe deleted successfully"}


@router.post("/recipes/{recipe_id}/ingredients", status_code=status.HTTP_201_CREATED)
async def add_recipe_ingredient(recipe_id: PositivePath, body: RecipeIngredientAdd):
    async with connection() as conn:
        row = await conn.fetchrow(
            """INSERT INTO recipe_ingredients(recipe_id,ingredient_id,quantity,unit)
               VALUES($1,$2,$3,$4)
               ON CONFLICT(recipe_id,ingredient_id) DO UPDATE
               SET quantity=EXCLUDED.quantity, unit=EXCLUDED.unit
               RETURNING recipe_id,ingredient_id,quantity,unit""",
            recipe_id, body.ingredient_id, body.quantity, body.unit,
        )
    return _decimal_fields(row, "quantity")


@router.delete("/recipes/{recipe_id}/ingredients/{ingredient_id}")
async def remove_recipe_ingredient(recipe_id: PositivePath, ingredient_id: PositivePath):
    async with connection() as conn:
        deleted = await conn.fetchval(
            """DELETE FROM recipe_ingredients WHERE recipe_id=$1 AND ingredient_id=$2
               RETURNING ingredient_id""",
            recipe_id, ingredient_id,
        )
    if not deleted:
        raise HTTPException(404, "Recipe ingredient not found")
    return {"message": "Ingredient removed"}


@router.get("/recipes/{recipe_id}/availability")
async def recipe_availability(recipe_id: PositivePath):
    async with connection() as conn:
        exists = await conn.fetchval("SELECT EXISTS(SELECT 1 FROM recipes WHERE id=$1)", recipe_id)
        if not exists:
            raise HTTPException(404, "Recipe not found")
        rows = await conn.fetch(
            """SELECT i.name AS ingredient_name, ri.quantity AS needed_quantity,
                      ri.unit AS needed_unit, COALESCE(inv.quantity,0) AS inventory_quantity,
                      inv.unit AS inventory_unit
               FROM recipe_ingredients ri
               JOIN ingredients i ON i.id=ri.ingredient_id
               LEFT JOIN inventory inv ON inv.ingredient_id=i.id
               WHERE ri.recipe_id=$1 ORDER BY i.name""",
            recipe_id,
        )
    available, low, missing = [], [], []
    for raw in rows:
        item = dict(raw)
        if item["inventory_quantity"] <= 0:
            target = missing
        elif (
            item["inventory_unit"] is None
            or item["inventory_unit"].strip().casefold()
            != item["needed_unit"].strip().casefold()
        ):
            target = missing
        elif item["inventory_quantity"] < item["needed_quantity"]:
            target = low
        else:
            target = available
        target.append(_decimal_fields(item, "needed_quantity", "inventory_quantity"))
    return {"can_make": not low and not missing, "available": available, "low": low, "missing": missing}


@router.get("/inventory")
async def list_inventory():
    async with connection() as conn:
        rows = await conn.fetch(f"{INVENTORY_SELECT} ORDER BY ing.name")
    return [_decimal_fields(row, "quantity", "min_quantity") for row in rows]


@router.post("/inventory", status_code=status.HTTP_201_CREATED)
async def create_inventory(body: InventoryCreate):
    async with connection() as conn:
        async with conn.transaction():
            ingredient_id = await conn.fetchval(
                """INSERT INTO ingredients(name,category,default_unit) VALUES($1,$2,$3)
                   ON CONFLICT(name) DO UPDATE SET category=EXCLUDED.category
                   RETURNING id""",
                body.name, body.category, body.unit,
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
            row = await conn.fetchrow(f"{INVENTORY_SELECT} WHERE inv.id=$1", item_id)
    return _decimal_fields(row, "quantity", "min_quantity")


@router.put("/inventory/{item_id}")
async def update_inventory(item_id: PositivePath, body: InventoryUpdate):
    changes = body.model_dump(exclude_unset=True)
    ingredient_changes = {k: changes.pop(k) for k in ("name", "category") if k in changes}
    async with connection() as conn:
        async with conn.transaction():
            ingredient_id = await conn.fetchval("SELECT ingredient_id FROM inventory WHERE id=$1", item_id)
            if not ingredient_id:
                raise HTTPException(404, "Inventory item not found")
            if ingredient_changes:
                values = list(ingredient_changes.values()) + [ingredient_id]
                assignments = [f"{key}=${i}" for i, key in enumerate(ingredient_changes, 1)]
                await conn.execute(
                    f"UPDATE ingredients SET {','.join(assignments)} WHERE id=${len(values)}",
                    *values,
                )
            if changes:
                values = list(changes.values()) + [item_id]
                assignments = [f"{key}=${i}" for i, key in enumerate(changes, 1)]
                await conn.execute(
                    f"UPDATE inventory SET {','.join(assignments)} WHERE id=${len(values)}",
                    *values,
                )
            row = await conn.fetchrow(f"{INVENTORY_SELECT} WHERE inv.id=$1", item_id)
    return _decimal_fields(row, "quantity", "min_quantity")


@router.delete("/inventory/{item_id}")
async def delete_inventory(item_id: PositivePath):
    async with connection() as conn:
        deleted = await conn.fetchval("DELETE FROM inventory WHERE id=$1 RETURNING id", item_id)
    if not deleted:
        raise HTTPException(404, "Inventory item not found")
    return {"message": "Inventory item deleted successfully"}


@router.get("/meal-plans")
async def list_meals():
    async with connection() as conn:
        rows = await conn.fetch(
            """SELECT me.id, me.meal_date AS date, me.meal_type, me.recipe_id,
                      r.name AS recipe_name, me.notes
               FROM meal_entries me LEFT JOIN recipes r ON r.id=me.recipe_id
               ORDER BY me.meal_date, me.meal_type"""
        )
    return [dict(row) for row in rows]


@router.post("/meal-plans", status_code=status.HTTP_201_CREATED)
async def create_meal(body: MealCreate):
    async with connection() as conn:
        row = await conn.fetchrow(
            """INSERT INTO meal_entries(meal_date,meal_type,recipe_id,notes)
               VALUES($1,$2,$3,$4) RETURNING id,meal_date AS date,meal_type,recipe_id,notes""",
            body.date, body.meal_type, body.recipe_id, body.notes,
        )
    return dict(row)


@router.post("/meal-plans/batch")
async def save_meal_batch(body: MealBatchRequest):
    item_ids = {item.id for item in body.items if item.id is not None}
    if item_ids.intersection(body.delete_ids):
        raise HTTPException(422, "A meal cannot be updated and deleted in the same batch")
    async with connection() as conn:
        async with conn.transaction():
            if body.delete_ids:
                await conn.execute("DELETE FROM meal_entries WHERE id=ANY($1::bigint[])", body.delete_ids)
            for item in body.items:
                if item.id is None:
                    await conn.execute(
                        """INSERT INTO meal_entries(meal_date,meal_type,recipe_id,notes)
                           VALUES($1,$2,$3,$4)""",
                        item.date, item.meal_type, item.recipe_id, item.notes,
                    )
                else:
                    updated = await conn.fetchval(
                        """UPDATE meal_entries SET meal_date=$1,meal_type=$2,recipe_id=$3,notes=$4
                           WHERE id=$5 RETURNING id""",
                        item.date, item.meal_type, item.recipe_id, item.notes, item.id,
                    )
                    if not updated:
                        raise HTTPException(404, f"Meal entry {item.id} not found")
    return {"status": "saved", "updated": len(item_ids), "created": len(body.items) - len(item_ids), "deleted": len(body.delete_ids)}


@router.put("/meal-plans/{meal_id}")
async def update_meal(meal_id: PositivePath, body: MealUpdate):
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        raise HTTPException(422, "No meal changes supplied")
    if "date" in changes:
        changes["meal_date"] = changes.pop("date")
    values = list(changes.values()) + [meal_id]
    assignments = [f"{key}=${index}" for index, key in enumerate(changes, 1)]
    async with connection() as conn:
        row = await conn.fetchrow(
            f"""UPDATE meal_entries SET {','.join(assignments)}
                WHERE id=${len(values)}
                RETURNING id,meal_date AS date,meal_type,recipe_id,notes""",
            *values,
        )
    if not row:
        raise HTTPException(404, "Meal entry not found")
    return dict(row)


@router.delete("/meal-plans/{meal_id}")
async def delete_meal(meal_id: PositivePath):
    async with connection() as conn:
        deleted = await conn.fetchval("DELETE FROM meal_entries WHERE id=$1 RETURNING id", meal_id)
    if not deleted:
        raise HTTPException(404, "Meal entry not found")
    return {"message": "Meal entry deleted"}
