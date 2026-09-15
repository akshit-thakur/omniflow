import asyncio
import json
import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .settings import get_settings


CLASSIFIER_WRITE_ACTION_NAMES = (
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

CLASSIFIER_WRITE_ACTIONS = """
- task.create arguments: title, description?, priority?, due_date?
- task.update arguments: selector id or task_id or task_title; changed fields
  title?, description?, priority?, completed?, due_date?
- task.complete arguments: selector id or task_id or task_title
- task.delete arguments: selector id or task_id or task_title
- medication.create arguments: name, common_dosage?, notes?
- medication.update arguments: selector id or medication_id or medication_name; changed
  fields name?, common_dosage?, notes?
- medication.log arguments: selector plan_id or plan_name or medication_id or
  medication_name; taken_at?, scheduled_time?, notes?
- medication.log.update arguments: selector id or log_id; plan selector plan_id or
  plan_name?; changed fields taken_at?, scheduled_time?, notes?
- medication.log.delete arguments: selector id or log_id
- medication.delete arguments: selector id or medication_id or medication_name
- medication.plan.create arguments: plan_name; medication selector medication_id or
  medication_name; dosage?, notes?, schedule_times?
- medication.plan.update arguments: selector id or plan_id or current_plan_name; changed fields
  plan_name?, medication_id or medication_name?, dosage?, notes?, active?, schedule_times?
- medication.plan.delete arguments: selector id or plan_id or plan_name
- exercise.create arguments: name, muscle_group or target_muscle_group?, equipment?,
  description? or notes?
- exercise.update arguments: selector id or exercise_id or exercise_name; changed fields
  name?, muscle_group or target_muscle_group?, equipment?, description? or notes?
- exercise.delete arguments: selector id or exercise_id or exercise_name
- training_set.create arguments: name, description?, exercises? as ordered objects with
  exercise_id or exercise_name or name
- training_set.update arguments: selector id or training_set_id or training_set_name;
  changed fields name?, description?, exercises?
- training_set.delete arguments: selector id or training_set_id or training_set_name
- workout.create arguments: training set selector training_set_id or template_id or
  training_set_name or template_name?; session_date?, duration_minutes?, name (1..200)?, notes?;
  exercises? with exercise_id or exercise_name or name, sets_completed?,
  reps_completed?, weight_kg?, sets?
- workout.update arguments: selector id or workout_id; changed fields training_set_id or
  template_id?, name?, session_date?, duration_minutes?, notes?, exercises?
- workout.delete arguments: selector id or workout_id
- recipe.create arguments: name, description?, instructions?, difficulty?, prep_time_minutes?
- recipe.update arguments: selector id or recipe_id or recipe_name; changed fields name?,
  description?, instructions?, difficulty?, prep_time_minutes?
- recipe.delete arguments: selector id or recipe_id or recipe_name
- recipe.ingredient.add arguments: recipe selector recipe_id or recipe_name; ingredient
  selector ingredient_id or ingredient_name; quantity, unit
- recipe.ingredient.remove arguments: recipe selector recipe_id or recipe_name;
  ingredient selector ingredient_id or ingredient_name
- ingredient.create arguments: name, category?, default_unit?
- ingredient.update arguments: selector id or ingredient_id or ingredient_name; changed
  fields name?, category?, default_unit?
- ingredient.delete arguments: selector id or ingredient_id or ingredient_name
- inventory.upsert arguments: ingredient selector name or ingredient_id or
  ingredient_name; quantity, unit?, category?, expiry_date?, min_quantity?
- inventory.adjust arguments: selector id or inventory_id or ingredient_id or
  ingredient_name; quantity_delta, unit?
- inventory.update arguments: selector id or inventory_id or ingredient_id or
  ingredient_name; changed fields name?, quantity?, unit?, category?, expiry_date?,
  min_quantity?
- inventory.delete arguments: selector id or inventory_id or ingredient_id or
  ingredient_name
- meal.create arguments: date, meal_type, recipe_id or recipe_name?, notes?
- meal.update arguments: selector id or meal_id; changed fields date?, meal_type?,
  recipe_id or recipe_name?, notes?
- meal.delete arguments: selector id or meal_id
- media.create arguments: title, media_type, status?, genre?, author_creator?,
  release_year (1000..9999)?, progress_current (>=0)?, progress_total (>=0)?,
  is_favorite?, notes?; progress_current cannot exceed progress_total
- media.update arguments: selector id or media_id or media_item_id or media_title;
  changed fields title?, media_type?, genre?, status?, author_creator?, release_year?,
  progress_current (>=0)?, progress_total (>=0)?, is_favorite?, rating?, notes?,
  review?; progress_current cannot exceed progress_total
- media.progress arguments: selector id or media_id or media_item_id or media_title;
  status?, progress_current (>=0)?, progress_total (>=0)?, rating? or rating_given?,
  notes?, review? or review_snapshot?; progress_current cannot exceed progress_total
- media.delete arguments: selector id or media_id or media_item_id or media_title
"""


class ClassifierAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal[CLASSIFIER_WRITE_ACTION_NAMES]  # type: ignore[valid-type]
    arguments: dict[str, Any] = Field(default_factory=dict)


class IntentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["read", "write", "chat"]


class ClassifierActionPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actions: list[ClassifierAction] = Field(default_factory=list, max_length=20)


class ClassifierResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["read", "write", "chat"]
    actions: list[ClassifierAction] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_action_intent(self) -> "ClassifierResponse":
        if self.intent == "write" and not self.actions:
            raise ValueError("write intent requires at least one action")
        if self.intent != "write" and self.actions:
            raise ValueError("read and chat intents cannot contain actions")
        return self


_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)
_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.IGNORECASE | re.DOTALL)
_JSON_START_RE = re.compile(r"[\[{]")


def _response_json(response: httpx.Response, runtime_name: str) -> dict[str, Any]:
    response.raise_for_status()
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{runtime_name} returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{runtime_name} returned an invalid response shape")
    return payload


def extract_json_value(raw: str) -> Any:
    """Extract one JSON value from plain, fenced, or prose-wrapped model output."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Model returned an empty JSON response")

    stripped = _THINK_BLOCK_RE.sub("", raw).strip()
    fenced = [match.group(1).strip() for match in _FENCED_JSON_RE.finditer(stripped)]
    candidates = [*fenced, stripped]
    decoder = json.JSONDecoder(parse_float=Decimal)

    for candidate in candidates:
        try:
            return json.loads(candidate, parse_float=Decimal)
        except json.JSONDecodeError:
            pass
        for match in _JSON_START_RE.finditer(candidate):
            try:
                value, _ = decoder.raw_decode(candidate[match.start():])
                return value
            except json.JSONDecodeError:
                continue
    raise ValueError("Model response did not contain valid JSON")


class ModelRuntime:
    """Process-wide Ollama client with an explicit FastAPI lifespan."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client
        self._owns_client = client is None
        self._client_lock = asyncio.Lock()

    async def start(self) -> None:
        async with self._client_lock:
            if self._client is not None and not self._client.is_closed:
                return
            if not self._owns_client:
                raise RuntimeError("The injected Ollama HTTP client is closed")
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(180.0, connect=10.0),
                limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
            )

    async def close(self) -> None:
        async with self._client_lock:
            if self._client is not None and self._owns_client:
                await self._client.aclose()
                self._client = None

    async def _session(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            await self.start()
        if self._client is None:
            raise RuntimeError("Ollama HTTP client is not initialized")
        return self._client

    async def tags(self) -> list[dict[str, Any]]:
        settings = get_settings()
        client = await self._session()
        response = await client.get(
            f"{settings.ollama_url}/api/tags",
            timeout=10.0,
        )
        payload = _response_json(response, "Tags runtime")
        models = payload.get("models", [])
        if not isinstance(models, list):
            raise RuntimeError("Tags runtime returned an invalid response shape")
        if any(not isinstance(item, dict) for item in models):
            raise RuntimeError("Tags runtime returned an invalid model entry")
        return models

    async def embeddings(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        settings = get_settings()
        client = await self._session()
        response = await client.post(
            f"{settings.ollama_url}/api/embed",
            json={"model": settings.embedding_model, "input": texts},
            timeout=180.0,
        )
        payload = _response_json(response, "Embedding runtime")
        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list):
            raise RuntimeError("Embedding runtime returned an invalid response shape")
        if len(embeddings) != len(texts):
            raise RuntimeError("Embedding runtime returned an unexpected batch size")
        if any(
            not isinstance(vector, list)
            or len(vector) != 1024
            or any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in vector
            )
            for vector in embeddings
        ):
            raise RuntimeError("bge-m3 index requires numeric 1024-dimensional embeddings")
        return embeddings

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool | dict[str, Any] = False,
        model: str | None = None,
    ) -> str:
        settings = get_settings()
        payload: dict[str, Any] = {
            "model": model or settings.reasoner_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": 0.1 if json_mode else 0.25, "top_p": 0.9},
        }
        if json_mode:
            payload["format"] = {"type": "object"} if json_mode is True else json_mode

        client = await self._session()
        response = await client.post(
            f"{settings.ollama_url}/api/chat",
            json=payload,
            timeout=180.0,
        )
        response_payload = _response_json(response, "Chat runtime")
        message = response_payload.get("message")
        if not isinstance(message, dict):
            raise RuntimeError("Chat runtime returned an invalid message")
        content = message.get("content", "")
        if not isinstance(content, str):
            raise RuntimeError("Chat runtime returned a non-text response")
        content = content.strip()
        if not content:
            raise RuntimeError("Chat runtime returned an empty response")
        if json_mode:
            return json.dumps(
                extract_json_value(content),
                separators=(",", ":"),
                default=str,
            )
        return content

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """Yield text fragments from Ollama without buffering the full answer."""
        settings = get_settings()
        client = await self._session()
        payload = {
            "model": model or settings.reasoner_model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": 0.25, "top_p": 0.9},
        }
        emitted = False
        async with client.stream(
            "POST",
            f"{settings.ollama_url}/api/chat",
            json=payload,
            timeout=180.0,
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if not line:
                    continue
                try:
                    item = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(
                        "Chat stream returned malformed JSON"
                    ) from exc
                if not isinstance(item, dict):
                    raise RuntimeError("Chat stream returned an invalid event")
                error = item.get("error")
                if error:
                    raise RuntimeError(f"Chat stream failed: {error}")
                message = item.get("message")
                if message is not None and not isinstance(message, dict):
                    raise RuntimeError("Chat stream returned an invalid message")
                content = message.get("content", "") if message else ""
                if not isinstance(content, str):
                    raise RuntimeError("Chat stream returned non-text content")
                if content:
                    emitted = True
                    yield content
        if not emitted:
            raise RuntimeError("Chat stream returned an empty response")

    async def classify(
        self,
        message: str,
        context: list[dict[str, Any]] | None = None,
        *,
        reference_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        intent_system = """Classify the current user's request for a personal dashboard.
Use only the current user message. No retrieved or stored content is available at
this trust stage, and no later context may change this decision.

Return intent=write only when the user explicitly asks to create, update, delete,
log, start, stop, pause, resume, complete, adjust, or otherwise mutate dashboard
data. Return intent=read for questions, searches, summaries, and reports. Return
intent=chat for conversation or requests that are neither reads nor mutations.
Return exactly one JSON object matching the supplied JSON Schema."""
        intent_raw = await self.chat(
            [
                {"role": "system", "content": intent_system},
                {"role": "user", "content": message},
            ],
            json_mode=IntentResponse.model_json_schema(),
        )
        intent = IntentResponse.model_validate(extract_json_value(intent_raw)).intent
        if intent != "write":
            return ClassifierResponse(intent=intent, actions=[]).model_dump(mode="json")

        safe_references = {
            key: value
            for key, value in (reference_context or {}).items()
            if isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
            and value > 0
        }
        tool_context = json.dumps(
            {"reference_context": safe_references},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        today = datetime.now().astimezone().date().isoformat()
        planner_system = f"""Plan allowlisted dashboard mutations after a separate,
trusted intent gate has already classified the user's message as an explicit write.
Return exactly one JSON object matching the supplied JSON Schema:
{{"actions":[{{"action":"...", "arguments":{{}}}}]}}

Plan only changes directly requested by the current user. Return every required
action in execution order. The entire array is committed atomically, so include
all parts of a composite request. If a requested mutation cannot be represented
with the allowlist and resolvable required values, return an empty actions array.

Allowed write actions are only:
{CLASSIFIER_WRITE_ACTIONS}

Use "$ref:context.<key>" only for a key that exists in the tool message's exact
"reference_context" object. The tool message contains only numeric IDs selected
by trusted code; do not invent context keys or database IDs. Entity names may be
used only when they appear in the current user's message and the action supports
that exact name selector. A prior action may be referenced through its execution
envelope, commonly "$ref:actions.0.entity_id" or "$ref:actions.0.result.id".

Preserve dependency order. Examples of composite requests include creating a
missing ingredient before adding it to a recipe, logging a meal before adjusting
inventory with a negative quantity_delta, and creating exercises before a workout
that names those exercises. Do not silently omit a requested sub-action.

For workout.create, default session_date to today's date ({today}) when the user
asks for today or gives no date. Map old media statuses this way: backlog -> to_watch, in_progress -> watching. All
questions, searches, summaries, and reports were handled by the trusted intent
gate."""
        plan_raw = await self.chat(
            [
                {"role": "system", "content": planner_system},
                {"role": "user", "content": message},
                {"role": "tool", "content": tool_context},
            ],
            json_mode=ClassifierActionPlan.model_json_schema(),
        )
        plan = ClassifierActionPlan.model_validate(extract_json_value(plan_raw))
        if not plan.actions:
            return ClassifierResponse(intent="chat", actions=[]).model_dump(mode="json")
        return ClassifierResponse(intent="write", actions=plan.actions).model_dump(mode="json")


runtime = ModelRuntime()
