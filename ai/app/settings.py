from dataclasses import dataclass
from functools import lru_cache
import math
import os


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
            raise RuntimeError(f"Unable to read {file_environment_name} at {path}") from exc
    else:
        raise RuntimeError(f"Required credential {environment_name} is not configured")
    if value.endswith("\r\n"):
        value = value[:-2]
    elif value.endswith("\n"):
        value = value[:-1]
    if not value.strip():
        raise RuntimeError(f"{environment_name} is empty or whitespace-only")
    if value.strip() in {
        "omniflow_password", "development-only-secret",
        "replace-with-a-strong-password", "replace-with-a-long-random-secret",
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


def _boolean(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(
        f"{name} must be true/false, yes/no, on/off, or 1/0"
    )


def _bounded_float(
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if not math.isfinite(value) or not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    database_host: str | None
    database_port: int
    database_name: str
    database_user: str
    database_password: str
    api_url: str
    ollama_url: str
    service_secret: str
    embedding_model: str
    reasoner_model: str
    index_version: int
    retrieval_limit: int
    max_semantic_distance: float
    sync_interval_seconds: int
    auto_reindex: bool


@lru_cache
def get_settings() -> Settings:
    embedding_model = (os.getenv("OLLAMA_EMBED_MODEL") or "bge-m3").strip()
    embedding_parts = embedding_model.split(":", 1)
    if embedding_parts[0] != "bge-m3" or (
        len(embedding_parts) == 2 and not embedding_parts[1]
    ):
        raise RuntimeError(
            "OLLAMA_EMBED_MODEL must be bge-m3 (optionally with a non-empty tag); "
            "the database vector contract is 1024-dimensional"
        )
    reasoner_model = (os.getenv("OLLAMA_REASONER_MODEL") or "qwen3:8b").strip()
    if not reasoner_model:
        raise RuntimeError("OLLAMA_REASONER_MODEL cannot be empty")
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
        api_url=os.getenv("API_INTERNAL_URL", "http://localhost:8001").rstrip("/"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        service_secret=_secret_value(
            "AI_SERVICE_SECRET",
            "AI_SERVICE_SECRET_FILE",
            None,
        ),
        embedding_model=embedding_model,
        reasoner_model=reasoner_model,
        index_version=_integer("INDEX_VERSION", 2, minimum=1, maximum=1_000_000),
        retrieval_limit=_integer("RETRIEVAL_LIMIT", 8, minimum=1, maximum=20),
        max_semantic_distance=_bounded_float(
            "MAX_SEMANTIC_DISTANCE",
            0.60,
            minimum=0.01,
            maximum=2.0,
        ),
        sync_interval_seconds=_integer(
            "INDEX_SYNC_INTERVAL_SECONDS",
            60,
            minimum=10,
            maximum=86_400,
        ),
        auto_reindex=_boolean("AUTO_REINDEX", True),
    )
