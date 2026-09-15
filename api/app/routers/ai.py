import hmac
import json
import logging
import hashlib
from collections.abc import AsyncIterator
from contextvars import ContextVar
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from ..db import connection

# Re-exported into this module's namespace on purpose: `execute_ai_action`
# calls the bare names, so `patch.object(app.routers.ai, "_execute_action", ...)`
# in tests/test_ai_actions.py still intercepts them. Do not rewrite those call
# sites as `mutations._execute_action(...)` — the patches would stop applying
# and the mutation tests would pass without exercising anything.
from ..mutations import (  # noqa: F401
    _ACTION_ARGUMENT_KEYS,
    _ENTITY_LOOKUPS,
    _RESULT_CONTEXT_IDS,
    _execute_action,
    _json,
    _prepare_action_arguments,
    _resolve_references,
    _update_execution_context,
)
from ..schemas import AIActionRequest, ChatRequest
from ..settings import get_settings

router = APIRouter()
logger = logging.getLogger(__name__)
_current_action_index: ContextVar[int | None] = ContextVar(
    "current_ai_action_index",
    default=None,
)


def _wire_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {key: _wire_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_wire_value(item) for item in value]
    return value


def _service_headers() -> dict[str, str]:
    return {"X-Omniflow-Secret": get_settings().service_secret}


@router.get("/ai/health")
async def ai_health():
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(
                f"{get_settings().ai_service_url}/health",
                headers=_service_headers(),
            )
        payload = response.json()
        return JSONResponse(status_code=response.status_code, content=payload)
    except (httpx.HTTPError, ValueError):
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "ollama_available": False,
                "error": "AI service unavailable",
            },
        )


@router.get("/ai/models")
async def ai_models():
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{get_settings().ai_service_url}/models",
                headers=_service_headers(),
            )
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        return {"models": []}


@router.post("/ai/agent/chat")
async def ai_chat(body: ChatRequest):
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                f"{get_settings().ai_service_url}/internal/chat",
                headers=_service_headers(),
                json=body.model_dump(mode="json"),
            )
        response.raise_for_status()
        return response.json()
    except httpx.TimeoutException:
        return {"success": False, "error": "AI request timed out"}
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("AI service unavailable: %s", exc)
        return {"success": False, "error": "AI service temporarily unavailable"}


async def _proxy_ai_chat_stream(body: ChatRequest) -> AsyncIterator[bytes]:
    try:
        timeout = httpx.Timeout(190.0, connect=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{get_settings().ai_service_url}/internal/chat/stream",
                headers=_service_headers(),
                json=body.model_dump(mode="json"),
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    yield chunk
    except httpx.TimeoutException:
        yield json.dumps(
            {"type": "error", "error": "The local AI request timed out."},
            separators=(",", ":"),
        ).encode() + b"\n"
    except httpx.HTTPError as exc:
        logger.warning("AI stream unavailable: %s", exc)
        yield json.dumps(
            {
                "type": "error",
                "error": "The local AI service is temporarily unavailable.",
            },
            separators=(",", ":"),
        ).encode() + b"\n"


@router.post("/ai/agent/chat/stream")
async def ai_chat_stream(body: ChatRequest):
    return StreamingResponse(
        _proxy_ai_chat_stream(body),
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
        },
    )


async def _run_action_batch(conn, body: AIActionRequest) -> dict[str, Any]:
    """Validate and execute one approved action batch on the caller's transaction."""
    execution_context = body.context.model_dump(exclude_none=True)
    execution_results: list[dict[str, Any]] = []
    for current_index, proposal in enumerate(body.actions):
        _current_action_index.set(current_index)
        referenced_arguments = _resolve_references(
            proposal.arguments,
            execution_context,
            execution_results,
        )
        resolved_arguments = await _prepare_action_arguments(
            conn,
            proposal.action,
            referenced_arguments,
        )
        table, entity_id, before, after = await _execute_action(
            conn,
            proposal.action,
            resolved_arguments,
        )
        resolved_arguments = _wire_value(resolved_arguments)
        before = _wire_value(before)
        after = _wire_value(after)
        audit_id = await conn.fetchval(
            """INSERT INTO ai_mutation_audit(
                 request_id,action_index,action,entity_table,entity_id,
                 arguments,before_state,after_state,status
               ) VALUES(
                 $1,$2,$3,$4,$5,$6::jsonb,$7::jsonb,$8::jsonb,'committed'
               ) RETURNING id""",
            body.request_id,
            current_index,
            proposal.action,
            table,
            entity_id,
            _json(resolved_arguments),
            _json(before) if before is not None else None,
            _json(after) if after is not None else None,
        )
        result = {
            "action_index": current_index,
            "action": proposal.action,
            "entity_table": table,
            "entity_id": entity_id,
            "arguments": resolved_arguments,
            "result": after,
            "audit_id": audit_id,
        }
        execution_results.append(result)
        _update_execution_context(execution_context, table, entity_id, after)

    response: dict[str, Any] = {
        "success": True,
        "request_id": str(body.request_id),
        "results": execution_results,
        "audit_ids": [item["audit_id"] for item in execution_results],
    }
    if len(execution_results) == 1:
        # Preserve the currently deployed AI service's single-action response
        # contract until it begins sending/reading ordered batches.
        only = execution_results[0]
        response.update(
            {
                "action": only["action"],
                "entity_id": only["entity_id"],
                "result": only["result"],
                "audit_id": only["audit_id"],
            }
        )
    return response


def _translate_action_error(exc: Exception) -> HTTPException:
    current_index = _current_action_index.get()
    if isinstance(exc, HTTPException):
        detail = (
            {**exc.detail, "action_index": current_index}
            if isinstance(exc.detail, dict)
            else {"message": str(exc.detail), "action_index": current_index}
        )
        return HTTPException(exc.status_code, detail, headers=exc.headers)
    if isinstance(exc, ValidationError):
        return HTTPException(
            422,
            {
                "message": "Invalid action arguments",
                "action_index": current_index,
                "errors": [
                    {
                        "loc": list(error["loc"]),
                        "msg": error["msg"],
                        "type": error["type"],
                    }
                    for error in exc.errors(include_url=False)
                ],
            },
        )
    return HTTPException(
        422,
        {
            "message": "Invalid action arguments",
            "action_index": current_index,
            "error": str(exc),
        },
    )


def _require_service_secret(value: str | None) -> None:
    if not value or not hmac.compare_digest(value, get_settings().service_secret):
        raise HTTPException(401, "Invalid service secret")


def _proposal_response(request_row, action_rows) -> dict[str, Any]:
    return {
        "request_id": str(request_row["request_id"]),
        "status": request_row["status"],
        "proposed_at": request_row["proposed_at"],
        "decided_at": request_row["decided_at"],
        "review": _json_object(request_row["review"], "proposal review") if request_row.get("review") is not None else None,
        "review_digest": request_row.get("review_digest"),
        "actions": [
            {
                "action_index": row["action_index"],
                "action": row["action"],
                "arguments": _json_object(row["arguments"], "proposal arguments"),
            }
            for row in action_rows
        ],
    }


def _review_digest(review: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(review, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def _operator_attribution(request: Request | None) -> str:
    """Store only a one-way attribution identifier, never the bearer token."""
    token = request.headers.get("authorization", "") if request is not None else ""
    return hashlib.sha256(token.encode()).hexdigest()


_REVIEW_TARGETS = {
    "task": ("tasks", "title"), "medication": ("medications", "name"),
    "plan": ("medication_plans", "plan_name"), "exercise": ("exercise_catalog", "name"),
    "training_set": ("training_sets", "name"), "recipe": ("recipes", "name"),
    "ingredient": ("ingredients", "name"), "media": ("media_items", "title"),
}


async def _build_review(conn, context: dict[str, Any], actions: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    """Build a read-only, API-owned review; never execute a domain mutation."""
    reviewed: list[dict[str, Any]] = []
    context_targets: list[dict[str, Any]] = []
    context_specs = {
        "task_id": ("tasks", "title"), "medication_id": ("medications", "name"),
        "plan_id": ("medication_plans", "plan_name"), "exercise_id": ("exercise_catalog", "name"),
        "training_set_id": ("training_sets", "name"), "workout_id": ("workout_sessions", "set_name"),
        "recipe_id": ("recipes", "name"), "ingredient_id": ("ingredients", "name"),
        "inventory_id": ("inventory", "name"), "meal_id": ("meal_entries", "id"),
        "media_id": ("media_items", "title"),
    }
    for key, (table, name_column) in context_specs.items():
        value = context.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            if table == "inventory":
                row = await conn.fetchrow("SELECT inv.id,ing.name AS display_name FROM inventory inv JOIN ingredients ing ON ing.id=inv.ingredient_id WHERE inv.id=$1", value)
            elif table == "meal_entries":
                row = await conn.fetchrow("SELECT id,('meal #' || id::text) AS display_name FROM meal_entries WHERE id=$1", value)
            else:
                row = await conn.fetchrow(f"SELECT id,{name_column} AS display_name FROM {table} WHERE id=$1", value)
            if row:
                context_targets.append({"context_key": key, "table": table, "id": row["id"], "name": row["display_name"]})
    for index, item in enumerate(actions):
        args = item["arguments"]
        display_args = json.loads(json.dumps(args, default=str))
        targets: list[dict[str, Any]] = []
        entity = item["action"].split(".", 1)[0]
        if item["action"].startswith("medication.plan."):
            entity = "plan"
        target_spec = _REVIEW_TARGETS.get(entity)
        if target_spec and item["action"].split(".")[-1] not in {"create", "upsert"}:
            table, name_column = target_spec
            candidate_id = next((args.get(key) for key in ("id", f"{entity}_id", "media_item_id") if isinstance(args.get(key), int) and not isinstance(args.get(key), bool)), None)
            selector_names = {
                "task": ("task_title", "title"),
                "media": ("media_title", "title"),
                "plan": ("plan_name", "plan_name"),
            }.get(entity, (f"{entity}_name", name_column, "name", "title"))
            candidate_name = next((args.get(key) for key in selector_names if isinstance(args.get(key), str) and args.get(key).strip()), None)
            row = None
            if candidate_id is not None:
                row = await conn.fetchrow(f"SELECT id,{name_column} AS display_name FROM {table} WHERE id=$1", candidate_id)
            elif candidate_name:
                row = await conn.fetchrow(f"SELECT id,{name_column} AS display_name FROM {table} WHERE lower(btrim({name_column}))=lower(btrim($1))", candidate_name)
            if row:
                targets.append({"table": table, "id": row["id"], "name": row["display_name"]})
        dependencies = []
        for value in _walk_values(args):
            if isinstance(value, str) and value.startswith("$ref:actions."):
                try:
                    dependency = int(value.split(".", 2)[1])
                except (ValueError, IndexError):
                    continue
                if dependency < index:
                    dependencies.append(dependency)
        reviewed.append({"action_index": index, "action": item["action"], "arguments": display_args, "targets": targets, "depends_on_actions": sorted(set(dependencies))})
    review = {"version": 1, "context_targets": context_targets, "actions": reviewed}
    return review, _review_digest(review)


def _walk_values(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _json_object(value: Any, label: str) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = __import__("json").loads(value)
        except ValueError as exc:
            raise HTTPException(500, f"Stored {label} are invalid") from exc
    if not isinstance(value, dict):
        raise HTTPException(500, f"Stored {label} are invalid")
    return value


@router.post("/internal/ai/proposals", status_code=201)
async def create_ai_proposal(
    body: AIActionRequest,
    x_omniflow_secret: str | None = Header(default=None),
):
    """Persist an AI proposal without mutating domain data."""
    _require_service_secret(x_omniflow_secret)
    context = body.context.model_dump(mode="json", exclude_none=True)
    async with connection() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                """INSERT INTO ai_action_requests(request_id,context)
                   VALUES($1,$2::jsonb)
                   RETURNING request_id,status,proposed_at,decided_at""",
                body.request_id,
                _json(context),
            )
            await conn.executemany(
                """INSERT INTO ai_action_proposals(request_id,action_index,action,arguments)
                   VALUES($1,$2,$3,$4::jsonb)""",
                [
                    (body.request_id, index, proposal.action, _json(proposal.arguments))
                    for index, proposal in enumerate(body.actions)
                ],
            )
            review, digest = await _build_review(
                conn, context, [{"action": p.action, "arguments": p.arguments} for p in body.actions]
            )
            await conn.execute(
                "UPDATE ai_action_requests SET review=$2::jsonb,review_digest=$3 WHERE request_id=$1",
                body.request_id, _json(review), digest,
            )
    row = {**dict(row), "review": review, "review_digest": digest}
    return _proposal_response(
        row,
        [
            {
                "action_index": index,
                "action": proposal.action,
                "arguments": proposal.arguments,
            }
            for index, proposal in enumerate(body.actions)
        ],
    )


async def _load_proposal(conn, request_id: UUID, *, lock: bool = False):
    suffix = " FOR UPDATE" if lock else ""
    request_row = await conn.fetchrow(
        """SELECT request_id,status,context,review,review_digest,proposed_at,decided_at,decided_by
           FROM ai_action_requests WHERE request_id=$1""" + suffix,
        request_id,
    )
    if not request_row:
        raise HTTPException(404, "AI proposal not found")
    action_rows = await conn.fetch(
        """SELECT action_index,action,arguments FROM ai_action_proposals
           WHERE request_id=$1 ORDER BY action_index""",
        request_id,
    )
    return request_row, action_rows


@router.get("/ai/proposals/{request_id}")
async def get_ai_proposal(request_id: UUID):
    async with connection() as conn:
        request_row, action_rows = await _load_proposal(conn, request_id)
    return _proposal_response(request_row, action_rows)


@router.get("/ai/proposals")
async def list_ai_proposals(
    status_filter: str = Query(default="pending", alias="status"),
):
    if status_filter not in {"pending", "committed", "rejected"}:
        raise HTTPException(422, "Invalid proposal status")
    async with connection() as conn:
        request_rows = await conn.fetch(
            """SELECT request_id,status,context,review,review_digest,proposed_at,decided_at,decided_by
               FROM ai_action_requests WHERE status=$1
               ORDER BY proposed_at DESC LIMIT 100""",
            status_filter,
        )
        result = []
        for request_row in request_rows:
            action_rows = await conn.fetch(
                """SELECT action_index,action,arguments FROM ai_action_proposals
                   WHERE request_id=$1 ORDER BY action_index""",
                request_row["request_id"],
            )
            result.append(_proposal_response(request_row, action_rows))
    return result


@router.post("/ai/proposals/{request_id}/approve")
async def approve_ai_proposal(request_id: UUID, request: Request = None):
    """Apply a pending proposal only after this explicit local-user approval."""
    try:
        async with connection() as conn:
            async with conn.transaction():
                request_row, action_rows = await _load_proposal(conn, request_id, lock=True)
                if request_row["status"] != "pending":
                    raise HTTPException(409, f"AI proposal is already {request_row['status']}")
                stored_review = _json_object(request_row.get("review"), "proposal review") if request is not None and request_row.get("review") is not None else None
                supplied_digest = request.headers.get("x-omniflow-review-digest") if request is not None else None
                if request is not None and (not stored_review or not supplied_digest or not hmac.compare_digest(supplied_digest, request_row.get("review_digest") or "")):
                    raise HTTPException(409, "Proposal requires a fresh review before approval")
                body = AIActionRequest.model_validate(
                    {
                        "request_id": str(request_id),
                        "context": _json_object(request_row["context"], "proposal context"),
                        "actions": [
                            {
                                "action": row["action"],
                                "arguments": _json_object(row["arguments"], "proposal arguments"),
                            }
                            for row in action_rows
                        ],
                    }
                )
                fresh_review, fresh_digest = await _build_review(
                    conn,
                    body.context.model_dump(exclude_none=True),
                    [
                        {"action": row["action"], "arguments": _json_object(row["arguments"], "proposal arguments")}
                        for row in action_rows
                    ],
                )
                if request is not None and not hmac.compare_digest(fresh_digest, request_row.get("review_digest") or ""):
                    raise HTTPException(409, "Proposal targets changed; review it again")
                response = await _run_action_batch(conn, body)
                await conn.execute(
                    """UPDATE ai_action_requests
                       SET status='committed',decided_at=CURRENT_TIMESTAMP,decided_by=$2
                       WHERE request_id=$1""",
                    request_id, _operator_attribution(request),
                )
    except (HTTPException, ValidationError, TypeError, ValueError, OverflowError) as exc:
        raise _translate_action_error(exc) from exc
    response["status"] = "committed"
    response["message"] = f"Applied {len(response['results'])} approved action(s)."
    return response


@router.post("/ai/proposals/{request_id}/reject")
async def reject_ai_proposal(request_id: UUID, request: Request = None):
    async with connection() as conn:
        row = await conn.fetchrow(
            """UPDATE ai_action_requests
               SET status='rejected',decided_at=CURRENT_TIMESTAMP,decided_by=$2
               WHERE request_id=$1 AND status='pending'
               RETURNING request_id,status,proposed_at,decided_at""",
            request_id, _operator_attribution(request),
        )
        if not row:
            existing = await conn.fetchval(
                "SELECT status FROM ai_action_requests WHERE request_id=$1",
                request_id,
            )
            if existing is None:
                raise HTTPException(404, "AI proposal not found")
            raise HTTPException(409, f"AI proposal is already {existing}")
    return {"request_id": str(request_id), "status": "rejected"}


async def execute_ai_action(
    body: AIActionRequest,
    x_omniflow_secret: str | None = Header(default=None),
):
    """Test/internal helper for executing a prevalidated batch; not an HTTP route."""
    _require_service_secret(x_omniflow_secret)
    try:
        async with connection() as conn:
            async with conn.transaction():
                return await _run_action_batch(conn, body)
    except (HTTPException, ValidationError, TypeError, ValueError, OverflowError) as exc:
        raise _translate_action_error(exc) from exc
