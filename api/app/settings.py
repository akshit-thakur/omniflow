from dataclasses import dataclass
from functools import lru_cache
import math
import os
from .credentials import read_credential


def _secret_value(
    environment_name: str,
    file_environment_name: str,
    default: str | None = None,
) -> str:
    direct = os.getenv(environment_name)
    path = os.getenv(file_environment_name)
    if direct is not None and path:
        raise RuntimeError(
            f"Configure only {environment_name} or {file_environment_name}, not both"
        )
    if direct is not None:
        value = direct
    elif path:
        try:
            with open(path, encoding="utf-8") as secret_file:
                value = secret_file.read()
        except OSError as exc:
            raise RuntimeError(
                f"Unable to read {file_environment_name} at {path}"
            ) from exc
    else:
        raise RuntimeError(f"Required credential {environment_name} is not configured")
    if value.endswith("\r\n"):
        value = value[:-2]
    elif value.endswith("\n"):
        value = value[:-1]
    if not value.strip():
        raise RuntimeError(f"{environment_name} is empty or whitespace-only")
    if value.strip() in {
        "omniflow_password",
        "development-only-secret",
        "replace-with-a-strong-password",
        "replace-with-a-long-random-secret",
    }:
        raise RuntimeError(f"{environment_name} contains a known placeholder")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise RuntimeError(
            f"{file_environment_name} must contain exactly one line"
        )
    return value


def _integer(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


def _positive_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or value <= 0:
        raise RuntimeError(f"{name} must be a finite number greater than zero")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    database_host: str | None
    database_port: int
    database_name: str
    database_user: str
    database_password: str
    ai_service_url: str
    service_secret: str
    operator_password: str
    allowed_hosts: tuple[str, ...]
    session_cookie_secure: bool
    pool_min_size: int
    pool_max_size: int
    db_command_timeout: float


@lru_cache
def get_settings() -> Settings:
    pool_min_size = _integer("DB_POOL_MIN_SIZE", 2, minimum=1, maximum=100)
    pool_max_size = _integer("DB_POOL_MAX_SIZE", 10, minimum=1, maximum=100)
    if pool_min_size > pool_max_size:
        raise RuntimeError("DB_POOL_MIN_SIZE cannot exceed DB_POOL_MAX_SIZE")
    return Settings(
        database_url=os.getenv("DATABASE_URL", ""),
        database_host=os.getenv("DATABASE_HOST"),
        database_port=_integer("DATABASE_PORT", 5432, minimum=1, maximum=65535),
        database_name=os.getenv("DATABASE_NAME", ""),
        database_user=os.getenv("DATABASE_USER", ""),
        database_password=_secret_value(
            "DATABASE_PASSWORD",
            "DATABASE_PASSWORD_FILE",
            None,
        ),
        ai_service_url=os.getenv("AI_SERVICE_URL", "http://localhost:8090").rstrip("/"),
        service_secret=_secret_value(
            "AI_SERVICE_SECRET",
            "AI_SERVICE_SECRET_FILE",
            None,
        ),
        operator_password=read_credential(),
        allowed_hosts=tuple(
            item.strip().lower()
            for item in os.getenv(
                "OMNIFLOW_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,api"
            ).split(",")
            if item.strip()
        ),
        session_cookie_secure=os.getenv("OMNIFLOW_SESSION_COOKIE_SECURE", "false").lower()
        in {"1", "true", "yes", "on"},
        pool_min_size=pool_min_size,
        pool_max_size=pool_max_size,
        db_command_timeout=_positive_float("DB_COMMAND_TIMEOUT", 30),
    )
