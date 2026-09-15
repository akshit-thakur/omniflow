from __future__ import annotations

from datetime import date, date as Date, datetime, time
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


Trimmed50 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
]
Trimmed100 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
Trimmed200 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
Trimmed300 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=300),
]
Trimmed500 = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]
PositiveInt = Annotated[int, Field(gt=0, strict=True)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _canonical_choice(value, allowed: tuple[str, ...]):
    if not isinstance(value, str):
        return value
    normalized = value.strip().replace("-", "_").replace(" ", "_").casefold()
    for choice in allowed:
        if normalized == choice.casefold():
            return choice
    return value


TASK_PRIORITIES = ("low", "medium", "high")
RECIPE_DIFFICULTIES = ("Easy", "Medium", "Hard")
MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")
MEDIA_TYPE_VALUES = (
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
)
MEDIA_STATUS_VALUES = (
    "to_watch",
    "watching",
    "completed",
    "on_hold",
    "dropped",
    "plan_to_watch",
)


class TaskCreate(StrictModel):
    title: Trimmed500
    description: str | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    due_date: date | None = None

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value):
        return _canonical_choice(value, TASK_PRIORITIES)


class TaskUpdate(StrictModel):
    title: Trimmed500 | None = None
    description: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    completed: bool | None = None
    due_date: date | None = None

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_priority(cls, value):
        return _canonical_choice(value, TASK_PRIORITIES)

    @field_validator("title", "priority", "completed")
    @classmethod
    def reject_null_required_columns(cls, value):
        if value is None:
            raise ValueError("field may be omitted but cannot be null")
        return value


class MedicationCreate(StrictModel):
    name: Trimmed200
    common_dosage: str | None = None
    notes: str | None = None


class MedicationUpdate(StrictModel):
    name: Trimmed200 | None = None
    common_dosage: str | None = None
    notes: str | None = None

    @field_validator("name")
    @classmethod
    def reject_null_name(cls, value):
        if value is None:
            raise ValueError("name may be omitted but cannot be null")
        return value


class MedicationPlanCreate(StrictModel):
    plan_name: Trimmed200
    medication_id: PositiveInt
    dosage: str | None = None
    notes: str | None = None
    schedule_times: list[time] = Field(default_factory=list, max_length=24)


class MedicationPlanUpdate(StrictModel):
    plan_name: Trimmed200 | None = None
    medication_id: PositiveInt | None = None
    dosage: str | None = None
    notes: str | None = None
    active: bool | None = None
    schedule_times: list[time] | None = Field(default=None, max_length=24)

    @field_validator("plan_name", "medication_id", "active")
    @classmethod
    def reject_null_required_columns(cls, value):
        if value is None:
            raise ValueError("field may be omitted but cannot be null")
        return value


class MedicationLogCreate(StrictModel):
    plan_id: PositiveInt
    taken_at: datetime | None = None
    scheduled_time: time | None = None
    notes: str | None = None


class MedicationLogUpdate(StrictModel):
    plan_id: PositiveInt | None = None
    taken_at: datetime | None = None
    scheduled_time: time | None = None
    notes: str | None = None

    @field_validator("plan_id", "taken_at")
    @classmethod
    def reject_null_required_columns(cls, value):
        if value is None:
            raise ValueError("field may be omitted but cannot be null")
        return value


class ExerciseCreate(StrictModel):
    name: Trimmed200
    muscle_group: Trimmed100
    equipment: str | None = None
    description: str | None = None


class ExerciseUpdate(StrictModel):
    name: Trimmed200 | None = None
    muscle_group: Trimmed100 | None = None
    equipment: str | None = None
    description: str | None = None

    @field_validator("name", "muscle_group")
    @classmethod
    def reject_null_required_columns(cls, value):
        if value is None:
            raise ValueError("field may be omitted but cannot be null")
        return value


class TrainingSetExercise(StrictModel):
    exercise_id: PositiveInt


class TrainingSetCreate(StrictModel):
    name: Trimmed200
    description: str | None = None
    exercises: list[TrainingSetExercise] = Field(default_factory=list, max_length=200)


class TrainingSetUpdate(StrictModel):
    name: Trimmed200 | None = None
    description: str | None = None
    exercises: list[TrainingSetExercise] | None = Field(default=None, max_length=200)

    @field_validator("name")
    @classmethod
    def reject_null_name(cls, value):
        if value is None:
            raise ValueError("name may be omitted but cannot be null")
        return value


class WorkoutExercise(StrictModel):
    exercise_id: PositiveInt | None = None
    exercise_name: Trimmed200 | None = None
    sets_completed: int = Field(default=0, ge=0)
    reps_completed: int | None = Field(default=None, ge=0)
    weight_kg: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=8,
        decimal_places=2,
    )
    sets: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class WorkoutCreate(StrictModel):
    training_set_id: PositiveInt | None = None
    name: Trimmed200 | None = None
    session_date: date
    duration_minutes: int | None = Field(default=None, ge=0)
    notes: str | None = None
    exercises: list[WorkoutExercise] = Field(default_factory=list, max_length=200)


class WorkoutUpdate(StrictModel):
    training_set_id: PositiveInt | None = None
    name: Trimmed200 | None = None
    session_date: date | None = None
    duration_minutes: int | None = Field(default=None, ge=0)
    notes: str | None = None
    exercises: list[WorkoutExercise] | None = Field(default=None, max_length=200)

    @field_validator("session_date")
    @classmethod
    def reject_null_session_date(cls, value):
        if value is None:
            raise ValueError("session_date may be omitted but cannot be null")
        return value


class IngredientCreate(StrictModel):
    name: Trimmed200
    category: str = "Other"
    default_unit: str = "piece"


class IngredientUpdate(StrictModel):
    name: Trimmed200 | None = None
    category: str | None = None
    default_unit: str | None = None

    @field_validator("name", "category", "default_unit")
    @classmethod
    def reject_null_required_columns(cls, value):
        if value is None:
            raise ValueError("field may be omitted but cannot be null")
        return value


class RecipeCreate(StrictModel):
    name: Trimmed300
    description: str | None = None
    instructions: str | None = None
    difficulty: Literal["Easy", "Medium", "Hard"] | None = None
    prep_time_minutes: int | None = Field(default=None, ge=0)

    @field_validator("difficulty", mode="before")
    @classmethod
    def normalize_difficulty(cls, value):
        return _canonical_choice(value, RECIPE_DIFFICULTIES)


class RecipeUpdate(StrictModel):
    name: Trimmed300 | None = None
    description: str | None = None
    instructions: str | None = None
    difficulty: Literal["Easy", "Medium", "Hard"] | None = None
    prep_time_minutes: int | None = Field(default=None, ge=0)

    @field_validator("difficulty", mode="before")
    @classmethod
    def normalize_difficulty(cls, value):
        return _canonical_choice(value, RECIPE_DIFFICULTIES)

    @field_validator("name")
    @classmethod
    def reject_null_name(cls, value):
        if value is None:
            raise ValueError("name may be omitted but cannot be null")
        return value


class RecipeIngredientAdd(StrictModel):
    ingredient_id: PositiveInt
    quantity: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    unit: Trimmed50


class InventoryCreate(StrictModel):
    name: Trimmed200
    quantity: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    unit: Trimmed50
    category: str = "Other"
    expiry_date: date | None = None
    min_quantity: Decimal = Field(
        default=Decimal("0"),
        ge=0,
        max_digits=10,
        decimal_places=2,
    )


class InventoryUpdate(StrictModel):
    name: Trimmed200 | None = None
    quantity: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=10,
        decimal_places=2,
    )
    unit: Trimmed50 | None = None
    category: str | None = None
    expiry_date: date | None = None
    min_quantity: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=10,
        decimal_places=2,
    )

    @field_validator("name", "quantity", "unit", "category", "min_quantity")
    @classmethod
    def reject_null_required_columns(cls, value):
        if value is None:
            raise ValueError("field may be omitted but cannot be null")
        return value


class InventoryAdjust(StrictModel):
    inventory_id: PositiveInt
    quantity_delta: Decimal = Field(max_digits=10, decimal_places=2)
    unit: Trimmed50 | None = None

    @field_validator("quantity_delta")
    @classmethod
    def reject_zero_delta(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("quantity_delta must be non-zero")
        return value


class MealCreate(StrictModel):
    date: date
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    recipe_id: PositiveInt | None = None
    notes: str | None = None

    @field_validator("meal_type", mode="before")
    @classmethod
    def normalize_meal_type(cls, value):
        return _canonical_choice(value, MEAL_TYPES)


class MealUpdate(StrictModel):
    date: Date | None = None
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] | None = None
    recipe_id: PositiveInt | None = None
    notes: str | None = None

    @field_validator("meal_type", mode="before")
    @classmethod
    def normalize_meal_type(cls, value):
        return _canonical_choice(value, MEAL_TYPES)

    @field_validator("date", "meal_type")
    @classmethod
    def reject_null_required_columns(cls, value):
        if value is None:
            raise ValueError("field may be omitted but cannot be null")
        return value


class MealBatchItem(StrictModel):
    id: PositiveInt | None = None
    date: date
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    recipe_id: PositiveInt | None = None
    notes: str | None = None

    @field_validator("meal_type", mode="before")
    @classmethod
    def normalize_meal_type(cls, value):
        return _canonical_choice(value, MEAL_TYPES)


class MealBatchRequest(StrictModel):
    items: list[MealBatchItem] = Field(max_length=100)
    delete_ids: list[PositiveInt] = Field(default_factory=list, max_length=100)


MEDIA_TYPES = Literal[
    "book", "movie", "tv_show", "video_game", "podcast", "documentary",
    "anime", "manga", "music_album", "audiobook",
]
MEDIA_STATUSES = Literal[
    "to_watch", "watching", "completed", "on_hold", "dropped", "plan_to_watch",
]


class MediaCreate(StrictModel):
    title: Trimmed500
    media_type: MEDIA_TYPES
    genre: str | None = None
    status: MEDIA_STATUSES = "to_watch"
    author_creator: str | None = None
    release_year: int | None = Field(default=None, ge=1000, le=9999)
    progress_current: int = Field(default=0, ge=0)
    progress_total: int | None = Field(default=None, ge=0)
    is_favorite: bool = False
    notes: str | None = None

    @field_validator("media_type", mode="before")
    @classmethod
    def normalize_media_type(cls, value):
        return _canonical_choice(value, MEDIA_TYPE_VALUES)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value):
        return _canonical_choice(value, MEDIA_STATUS_VALUES)

    @model_validator(mode="after")
    def validate_progress(self):
        if self.progress_total is not None and self.progress_current > self.progress_total:
            raise ValueError("progress_current cannot exceed progress_total")
        return self


class MediaUpdate(StrictModel):
    title: Trimmed500 | None = None
    media_type: MEDIA_TYPES | None = None
    genre: str | None = None
    status: MEDIA_STATUSES | None = None
    author_creator: str | None = None
    release_year: int | None = Field(default=None, ge=1000, le=9999)
    progress_current: int | None = Field(default=None, ge=0)
    progress_total: int | None = Field(default=None, ge=0)
    is_favorite: bool | None = None
    rating: int | None = Field(default=None, ge=1, le=10)
    notes: str | None = None
    review: str | None = None

    @field_validator("media_type", mode="before")
    @classmethod
    def normalize_media_type(cls, value):
        return _canonical_choice(value, MEDIA_TYPE_VALUES)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value):
        return _canonical_choice(value, MEDIA_STATUS_VALUES)

    @field_validator(
        "title",
        "media_type",
        "status",
        "progress_current",
        "is_favorite",
    )
    @classmethod
    def reject_null_required_columns(cls, value):
        if value is None:
            raise ValueError("field may be omitted but cannot be null")
        return value

    @model_validator(mode="after")
    def validate_progress(self):
        if (
            self.progress_current is not None
            and self.progress_total is not None
            and self.progress_current > self.progress_total
        ):
            raise ValueError("progress_current cannot exceed progress_total")
        return self


class BulkMedia(StrictModel):
    items: list[MediaCreate] = Field(min_length=1, max_length=500)


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=5000)


class ChatRequest(StrictModel):
    message: str = Field(min_length=1, max_length=5000)
    model: str | None = Field(default=None, max_length=100)
    include_context: bool = True
    # The browser owns the short-lived transcript; the API does not persist it.
    history: list[ChatMessage] = Field(default_factory=list, max_length=5)


AI_WRITE_ACTIONS = (
    "task.create",
    "task.update",
    "task.complete",
    "task.delete",
    "medication.create",
    "medication.update",
    "medication.log",
    "medication.log.update",
    "medication.log.delete",
    "medication.delete",
    "medication.plan.create",
    "medication.plan.update",
    "medication.plan.delete",
    "exercise.create",
    "exercise.update",
    "exercise.delete",
    "training_set.create",
    "training_set.update",
    "training_set.delete",
    "workout.create",
    "workout.update",
    "workout.delete",
    "recipe.create",
    "recipe.update",
    "recipe.delete",
    "recipe.ingredient.add",
    "recipe.ingredient.remove",
    "ingredient.create",
    "ingredient.update",
    "ingredient.delete",
    "inventory.upsert",
    "inventory.adjust",
    "inventory.update",
    "inventory.delete",
    "meal.create",
    "meal.update",
    "meal.delete",
    "media.create",
    "media.update",
    "media.progress",
    "media.delete",
)


class ActionProposal(StrictModel):
    action: Literal[AI_WRITE_ACTIONS]  # type: ignore[valid-type]
    arguments: dict[str, Any] = Field(default_factory=dict)


class AIActionContext(StrictModel):
    """Allowlisted values that action arguments may reference via `$ref:context.*`."""

    task_id: PositiveInt | None = None
    task_title: Trimmed500 | None = None
    medication_id: PositiveInt | None = None
    medication_name: Trimmed200 | None = None
    plan_id: PositiveInt | None = None
    plan_name: Trimmed200 | None = None
    medication_log_id: PositiveInt | None = None
    exercise_id: PositiveInt | None = None
    exercise_name: Trimmed200 | None = None
    training_set_id: PositiveInt | None = None
    training_set_name: Trimmed200 | None = None
    workout_id: PositiveInt | None = None
    recipe_id: PositiveInt | None = None
    recipe_name: Trimmed300 | None = None
    ingredient_id: PositiveInt | None = None
    ingredient_name: Trimmed200 | None = None
    inventory_id: PositiveInt | None = None
    meal_id: PositiveInt | None = None
    media_id: PositiveInt | None = None
    media_title: Trimmed500 | None = None


class AIActionRequest(StrictModel):
    """Ordered AI mutation batch.

    The before-validator preserves the deployed single-action wire contract while
    all internal execution uses the bounded `actions` list.
    """

    request_id: UUID
    actions: list[ActionProposal] = Field(min_length=1, max_length=20)
    context: AIActionContext = Field(default_factory=AIActionContext)

    @model_validator(mode="before")
    @classmethod
    def upgrade_legacy_single_action(cls, value):
        if not isinstance(value, dict):
            return value
        data = dict(value)
        legacy_action_present = "action" in data
        legacy_arguments_present = "arguments" in data
        legacy_action = data.pop("action", None)
        legacy_arguments = data.pop("arguments", None)
        if "actions" in data:
            if legacy_action_present or legacy_arguments_present:
                raise ValueError("use either actions or legacy action/arguments, not both")
            return data
        if not legacy_action_present:
            return data
        data["actions"] = [
            {
                "action": legacy_action,
                "arguments": {} if legacy_arguments is None else legacy_arguments,
            }
        ]
        return data

    @property
    def action(self):
        return self.actions[0].action if len(self.actions) == 1 else None

    @property
    def arguments(self) -> dict[str, Any] | None:
        return self.actions[0].arguments if len(self.actions) == 1 else None
