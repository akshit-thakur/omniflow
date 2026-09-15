"""Read-only-by-default smoke check for a running Omniflow stack."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PORT = 3001
DEFAULT_TIMEOUT = 10.0

DOMAIN_LIST_ENDPOINTS = (
    "/api/recipes/",
    "/api/recipes/ingredients",
    "/api/inventory",
    "/api/meal-plans",
    "/api/medications/catalog",
    "/api/medications/plans",
    "/api/medications/logs",
    "/api/gym/exercises",
    "/api/gym/sets",
    "/api/gym/history",
    "/api/media/",
)
INTERNAL_BLOCK_ENDPOINTS = (
    "/api/internal",
    "/api/internal/ai/proposals",
    "/api/internal/ai/actions",
)


@dataclass(frozen=True)
class RuntimeConfig:
    base_url: str


def _read_env_file(path: Path | None) -> dict[str, str]:
    """Read the few smoke settings from a Compose-style env file.

    This deliberately is not a general dotenv implementation. It accepts the
    ordinary unquoted and single/double-quoted values used by this repository,
    while process environment variables remain authoritative.
    """
    if path is None or not path.exists():
        return {}

    values: dict[str, str] = {}
    wanted = {"BASE_URL", "OMNIFLOW_PORT"}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        if key not in wanted:
            continue

        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        else:
            value = re.split(r"\s+#", value, maxsplit=1)[0].rstrip()
        values[key] = value
    return values


def resolve_runtime_config(
    *,
    base_url: str | None,
    env_file: Path | None,
    environ: Mapping[str, str] | None = None,
) -> RuntimeConfig:
    environment = os.environ if environ is None else environ
    file_values = _read_env_file(env_file)

    selected_base_url = (
        base_url
        or environment.get("BASE_URL")
        or file_values.get("BASE_URL")
    )
    if not selected_base_url:
        port_text = (
            environment.get("OMNIFLOW_PORT")
            if "OMNIFLOW_PORT" in environment
            else file_values.get("OMNIFLOW_PORT", str(DEFAULT_PORT))
        ) or str(DEFAULT_PORT)
        try:
            port = int(port_text)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"OMNIFLOW_PORT must be an integer, got {port_text!r}") from exc
        if not 1 <= port <= 65535:
            raise ValueError(f"OMNIFLOW_PORT must be between 1 and 65535, got {port}")
        selected_base_url = f"http://127.0.0.1:{port}"

    selected_base_url = selected_base_url.rstrip("/")
    parsed = urlsplit(selected_base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "BASE_URL/--base-url must be an absolute http(s) URL, "
            f"got {selected_base_url!r}"
        )

    return RuntimeConfig(base_url=selected_base_url)


class SmokeClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        opener: Callable[..., Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._opener = opener or urlopen
        self.cookies: dict[str, str] = {}

    def login(self, password: str) -> None:
        result = self.request("/api/auth/login", method="POST", body={"password": password})
        self.cookies["__bearer__"] = result["access_token"]
        self.cookies["__csrf__"] = result["csrf_token"]

    @staticmethod
    def _payload(raw: bytes) -> tuple[Any, str | None]:
        if not raw:
            return {}, None
        try:
            return json.loads(raw), None
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            preview = raw[:200].decode("utf-8", errors="replace")
            return None, f"invalid JSON ({exc}); response started with {preview!r}"

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: Any = None,
        expected: Sequence[int] = (200,),
        require_json: bool = True,
    ) -> Any:
        if not path.startswith("/"):
            raise ValueError(f"Smoke request path must start with '/': {path!r}")

        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Accept": "application/json"}
        if "__bearer__" in self.cookies:
            headers["Authorization"] = f"Bearer {self.cookies['__bearer__']}"
        if method in {"POST", "PUT", "PATCH", "DELETE"} and path != "/api/auth/login":
            headers["Origin"] = self.base_url
            if "__csrf__" in self.cookies:
                headers["X-CSRF-Token"] = self.cookies["__csrf__"]
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            f"{self.base_url}{path}",
            method=method,
            data=data,
            headers=headers,
        )
        try:
            with self._opener(request, timeout=self.timeout) as response:
                status = response.status
                for header in (getattr(response, "headers", None).get_all("Set-Cookie") if getattr(response, "headers", None) else []) or []:
                    pair = header.split(";", 1)[0]
                    key, value = pair.split("=", 1)
                    self.cookies[key] = value
                raw = response.read()
        except HTTPError as exc:
            status = exc.code
            raw = exc.read()
        except URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(f"{method} {path}: cannot reach {self.base_url}: {reason}") from exc

        payload, payload_error = self._payload(raw)
        if status not in expected:
            detail = payload if payload_error is None else payload_error
            raise RuntimeError(
                f"{method} {path}: expected HTTP {tuple(expected)}, got {status}: {detail}"
            )
        if payload_error is not None and require_json:
            raise RuntimeError(f"{method} {path}: HTTP {status} returned {payload_error}")

        print(f"ok HTTP  {method:6} {path} ({status})")
        return payload


def _require(condition: bool, label: str, payload: Any) -> None:
    if not condition:
        raise RuntimeError(f"{label} returned an unhealthy or invalid payload: {payload}")
    print(f"ok CHECK {label}")


def run_read_checks(client: SmokeClient) -> None:
    frontend = client.request("/healthz")
    _require(
        isinstance(frontend, dict)
        and frontend.get("status") == "healthy"
        and frontend.get("service") == "frontend",
        "frontend health",
        frontend,
    )

    smoke_password = os.getenv("SMOKE_OPERATOR_PASSWORD")
    if smoke_password:
        client.login(smoke_password)

    for endpoint in INTERNAL_BLOCK_ENDPOINTS:
        client.request(endpoint, expected=(404,), require_json=False)

    # This public domain read crosses Nginx -> API -> PostgreSQL, making it the
    # externally authoritative API/database readiness check.
    tasks = client.request("/api/tasks/")
    _require(isinstance(tasks, list), "API/database health", tasks)

    ai = client.request("/api/ai/health")
    _require(
        isinstance(ai, dict)
        and ai.get("status") == "healthy"
        and ai.get("service") == "ai"
        and ai.get("database_available") is True
        and ai.get("ollama_available") is True
        and ai.get("index_available") is True,
        "AI health",
        ai,
    )

    for endpoint in DOMAIN_LIST_ENDPOINTS:
        payload = client.request(endpoint)
        _require(isinstance(payload, list), f"list response for {endpoint}", payload)


def _positive_id(payload: Any, label: str) -> int:
    value = payload.get("id") if isinstance(payload, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RuntimeError(f"{label} did not return a positive integer id: {payload}")
    return value


def run_write_check(client: SmokeClient) -> None:
    print("WARNING: --write creates, updates, and deletes one task.", file=sys.stderr)
    task_id: int | None = None
    try:
        task = client.request(
            "/api/tasks/",
            method="POST",
            body={"title": f"smoke-{uuid4()}", "priority": "low"},
            expected=(201,),
        )
        task_id = _positive_id(task, "task create")

        fetched = client.request(f"/api/tasks/{task_id}")
        _require(
            isinstance(fetched, dict) and fetched.get("id") == task_id,
            "created task read",
            fetched,
        )

        updated = client.request(
            f"/api/tasks/{task_id}",
            method="PUT",
            body={"completed": True},
        )
        _require(
            isinstance(updated, dict)
            and updated.get("id") == task_id
            and updated.get("completed") is True,
            "created task update",
            updated,
        )
    finally:
        active_error = sys.exc_info()[0] is not None
        if task_id is not None:
            try:
                client.request(f"/api/tasks/{task_id}", method="DELETE")
            except Exception as cleanup_error:
                if not active_error:
                    raise
                print(
                    f"WARNING: cleanup of smoke task {task_id} also failed: "
                    f"{cleanup_error}",
                    file=sys.stderr,
                )


def _positive_timeout(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return parsed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        help=(
            "public Omniflow origin; defaults to BASE_URL, then OMNIFLOW_PORT "
            "from the process/.env, then http://127.0.0.1:3001"
        ),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=ROOT / ".env",
        help="Compose env file used for port selection (default: %(default)s)",
    )
    parser.add_argument(
        "--timeout",
        type=_positive_timeout,
        default=DEFAULT_TIMEOUT,
        help="per-request timeout in seconds (default: %(default)s)",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="also create/update/delete a task",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = resolve_runtime_config(
            base_url=args.base_url,
            env_file=args.env_file,
        )
        client = SmokeClient(
            config.base_url,
            timeout=args.timeout,
        )
        print(f"Checking Omniflow at {config.base_url}")
        run_read_checks(client)
        if args.write:
            run_write_check(client)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"Omniflow smoke check failed: {exc}", file=sys.stderr)
        return 1

    mode = "read/write" if args.write else "read-only"
    print(f"Omniflow {mode} smoke check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
