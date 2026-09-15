from contextlib import asynccontextmanager
import logging
import time
from uuid import uuid4

import asyncpg
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from .db import close_pool, open_pool, ready
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
        ("POST", "/api/internal/ai/proposals"),
    }
    if (request.method, request.url.path) not in public:
        try:
            require_operator(request)
        except HTTPException as exc:
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    return await call_next(request)


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
for module in (tasks, kitchen, medications, gym, media, backups, ai):
    app.include_router(module.router, prefix="/api")
