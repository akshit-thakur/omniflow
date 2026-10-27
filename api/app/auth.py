"""Local operator authentication and browser CSRF protection.

Sessions are server-side, short-lived bearer records.  The operator password is
only read by the API process; the AI service has no route or secret that can
create an operator session.
"""

from __future__ import annotations

import hmac
import secrets
import time
from urllib.parse import urlsplit
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .credentials import demo_mode, fingerprint, read_credential, set_password, verify

SESSION_TTL_SECONDS = 8 * 60 * 60
_sessions: dict[str, tuple[bytes, float]] = {}
_session_credentials: dict[str, bytes] = {}
MAX_SESSIONS = 1024
LOGIN_WINDOW_SECONDS = 60
MAX_LOGIN_FAILURES = 10
_login_failures: dict[str, list[float]] = {}
router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=512)


def _valid_host(request: Request) -> bool:
    host = request.url.hostname or ""
    allowed = {
        item.strip().lower()
        for item in __import__("os").getenv(
            "OMNIFLOW_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,api,frontend"
        ).split(",")
        if item.strip()
    }
    return host in allowed


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    if not origin:
        return False
    parsed = urlsplit(origin)
    allowed = {
        item.strip().lower()
        for item in __import__("os").getenv("OMNIFLOW_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,api,frontend").split(",")
        if item.strip()
    }
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in allowed:
        return False
    try:
        effective_port = parsed.port or (443 if parsed.scheme == "https" else 80)
        request_port = request.url.port or (443 if request.url.scheme == "https" else 80)
    except ValueError:
        return False
    return parsed.hostname == request.url.hostname and effective_port == request_port and parsed.path in {"", "/"}


def _session(request: Request) -> tuple[str, bytes] | None:
    authorization = request.headers.get("authorization", "")
    token = authorization.removeprefix("Bearer ").strip() if authorization.startswith("Bearer ") else ""
    item = _sessions.get(token or "")
    if not item:
        return None
    csrf, expires = item
    if expires <= time.time() or _session_credentials.get(token) != fingerprint():
        _sessions.pop(token or "", None)
        _session_credentials.pop(token or "", None)
        return None
    return token, csrf


def require_operator(request: Request) -> tuple[str, bytes]:
    if not _valid_host(request):
        raise HTTPException(400, "Unrecognized Host")
    if demo_mode():
        if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not _same_origin(request):
            raise HTTPException(403, "Invalid demo request origin")
        return "demo", b""
    session = _session(request)
    if not session:
        raise HTTPException(401, "Operator authentication required")
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        csrf = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(csrf, session[1].hex()) or not _same_origin(request):
            raise HTTPException(403, "CSRF validation failed")
    return session


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response):
    if not _valid_host(request):
        raise HTTPException(400, "Unrecognized Host")
    now = time.time()
    client = request.client.host if request.client else "unknown"
    failures = [stamp for stamp in _login_failures.get(client, []) if stamp > now - LOGIN_WINDOW_SECONDS]
    if len(failures) >= MAX_LOGIN_FAILURES:
        raise HTTPException(429, "Too many login attempts")
    credential = read_credential()
    if not verify(body.password, credential):
        failures.append(now)
        _login_failures[client] = failures
        raise HTTPException(401, "Invalid operator credential")
    _login_failures.pop(client, None)
    for token, (_, expires) in list(_sessions.items()):
        if expires <= now:
            _sessions.pop(token, None)
            _session_credentials.pop(token, None)
    if len(_sessions) >= MAX_SESSIONS:
        raise HTTPException(503, "Operator session capacity reached")
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_bytes(32)
    _sessions[token] = (csrf, time.time() + SESSION_TTL_SECONDS)
    _session_credentials[token] = fingerprint(credential)
    # A bearer token is intentionally returned to the same-origin SPA. Cookies
    # are not used: HTTP cookies are scoped by host/path, never by TCP port.
    return {"authenticated": True, "access_token": token, "csrf_token": csrf.hex()}


@router.get("/status")
async def status():
    return {"setup_required": not demo_mode() and not bool(read_credential()), "demo": demo_mode()}


@router.post("/setup")
async def setup(body: LoginRequest, request: Request, response: Response):
    if not _valid_host(request) or not _same_origin(request):
        raise HTTPException(403, "Setup requires a same-origin request")
    if demo_mode():
        raise HTTPException(409, "Demo does not require setup")
    try:
        set_password(body.password)
    except FileExistsError:
        raise HTTPException(409, "Operator is already configured")
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    return await login(body, request, response)


@router.get("/session")
async def session(request: Request):
    require_operator(request)
    return {"authenticated": True}


@router.post("/logout")
async def logout(request: Request, response: Response):
    token, _ = require_operator(request)
    _sessions.pop(token, None)
    _session_credentials.pop(token, None)
    return {"authenticated": False}
