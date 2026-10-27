from contextlib import asynccontextmanager
import logging
import time
from uuid import uuid4

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .db import close_pool, open_pool, ready, activity_source, connection
from .auth import router as auth_router, require_operator
from .routers import ai, backups, gym, kitchen, media, medications, tasks


logging.basicConfig(level=logging.INFO, force=True)
logger = logging.getLogger("omniflow.api")


@asynccontextmanager
async def lifespan(_: FastAPI):
    await open_pool()
    try:
        logger.info("API service started")
        yield
    finally:
        await close_pool()
        logger.info("API service stopped")


app = FastAPI(
    title="Omniflow API",
    version="3.0.0",
    default_response_class=JSONResponse,
    lifespan=lifespan,
)


@app.middleware("http")
async def operator_boundary(request: Request, call_next):
    # Liveness/readiness and the separately authenticated AI ingestion endpoint
    # are the only unauthenticated HTTP paths.  AI's browser-facing proxy still
    # requires the operator session.
    public = {
        ("GET", "/"), ("GET", "/health"), ("GET", "/live"),
        ("POST", "/api/auth/login"),
        ("GET", "/api/auth/status"), ("POST", "/api/auth/setup"),
        ("POST", "/api/internal/ai/proposals"),
    }
    if (request.method, request.url.path) not in public:
        try:
            require_operator(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    path = request.url.path
    source = "ai" if path.startswith('/api/ai/') else "restore" if path.startswith('/api/backups/') and path.endswith('/restore') else "manual"
    token = activity_source.set(source)
    try:
        return await call_next(request)
    finally:
        activity_source.reset(token)


@app.middleware("http")
async def request_log(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid4()))
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled request failure")
        raise
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "%s %s status=%s duration_ms=%s request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        round((time.monotonic() - started) * 1000, 2),
        request_id,
    )
    return response


@app.exception_handler(asyncpg.UniqueViolationError)
async def unique_violation(_: Request, exc: asyncpg.UniqueViolationError):
    return JSONResponse(status_code=409, content={"detail": "A record with those values already exists"})


@app.exception_handler(asyncpg.ForeignKeyViolationError)
async def foreign_key_violation(_: Request, exc: asyncpg.ForeignKeyViolationError):
    return JSONResponse(status_code=409, content={"detail": "The record is still referenced or its parent does not exist"})


@app.exception_handler(asyncpg.CheckViolationError)
async def check_violation(_: Request, exc: asyncpg.CheckViolationError):
    return JSONResponse(status_code=422, content={"detail": "One or more values violate a data constraint"})


@app.exception_handler(asyncpg.NotNullViolationError)
async def not_null_violation(_: Request, exc: asyncpg.NotNullViolationError):
    return JSONResponse(status_code=422, content={"detail": "A required value cannot be null"})


@app.exception_handler(asyncpg.DataError)
async def invalid_database_value(_: Request, exc: asyncpg.DataError):
    return JSONResponse(status_code=422, content={"detail": "One or more values have an invalid database representation"})


@app.get("/")
async def root():
    return {"message": "Omniflow API", "version": "3.0.0"}


@app.get("/health")
async def health():
    try:
        if await ready():
            return {"status": "healthy", "service": "api"}
    except Exception as exc:
        logger.warning("Database readiness check failed: %s", exc)
    return JSONResponse(status_code=503, content={"status": "unhealthy", "service": "api"})


@app.get("/live")
async def live():
    return {"status": "alive", "service": "api"}


app.include_router(auth_router, prefix="/api")


@app.get("/api/activity")
async def recent_activity(limit: int = 100, before: str | None = None, before_id: str = ""):
    from datetime import datetime
    if not 1 <= limit <= 200:
        raise HTTPException(422, "Limit must be between 1 and 200")
    try:
        cursor = datetime.fromisoformat(before) if before else None
        if cursor is not None and cursor.tzinfo is None:
            raise ValueError()
    except ValueError:
        raise HTTPException(422, "Invalid activity cursor")
    async with connection() as conn:
        rows = await conn.fetch("""
            SELECT * FROM (
              SELECT 'change-' || id AS id, created_at, 'Operator' AS actor,
                     source, action, entity_table, entity_id, label
              FROM activity_events
              UNION ALL
              SELECT 'ai-' || id, created_at, 'Operator', 'ai', action,
                     entity_table, entity_id,
                     COALESCE(after_state->>'title', after_state->>'name', before_state->>'title', before_state->>'name', entity_id)
              FROM ai_mutation_audit WHERE status = 'committed'
            ) events
            WHERE created_at >= now() - interval '7 days'
              AND ($2::timestamptz IS NULL OR (created_at, id) < ($2, $3))
            ORDER BY created_at DESC, id DESC LIMIT $1
        """, limit, cursor, before_id)
    return [dict(row) for row in rows]
for module in (tasks, kitchen, medications, gym, media, backups, ai):
    app.include_router(module.router, prefix="/api")
