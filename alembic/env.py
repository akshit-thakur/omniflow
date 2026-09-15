"""Alembic migration environment for OmniFlow.

Migrations are hand-written raw SQL (sourced from database/init.sql for the
initial revision). No SQLAlchemy ORM models are maintained, so target_metadata is
None and autogenerate is disabled.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from urllib.parse import quote

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

_db_url = os.getenv("DATABASE_URL")

if not _db_url:
    _user = os.getenv("DATABASE_USER") or os.getenv("DB_USER", "postgres")
    _password_file = os.getenv("DATABASE_PASSWORD_FILE")
    _password = os.getenv("DATABASE_PASSWORD")
    if _password is not None and _password_file:
        raise RuntimeError("Configure only DATABASE_PASSWORD or DATABASE_PASSWORD_FILE")
    if _password_file:
        try:
            with open(_password_file, encoding="utf-8") as password_file:
                _password = password_file.read().rstrip("\r\n")
        except OSError as exc:
            raise RuntimeError("Unable to read DATABASE_PASSWORD_FILE") from exc
    if not _password or not _password.strip():
        raise RuntimeError("A database password or password file is required")
    _host = os.getenv("DATABASE_HOST") or os.getenv("DB_HOST", "localhost")
    _port = os.getenv("DATABASE_PORT") or os.getenv("DB_PORT", "5432")
    _name = os.getenv("DATABASE_NAME") or os.getenv("DB_NAME", "omniflow")
    _encoded_user = quote(_user, safe="")
    _encoded_name = quote(_name, safe="")
    _url_host = _host
    if ":" in _url_host and not (
        _url_host.startswith("[") and _url_host.endswith("]")
    ):
        _url_host = f"[{_url_host}]"
    if _password:
        _auth = f"{_encoded_user}:{quote(_password, safe='')}@"
    else:
        _auth = f"{_encoded_user}@"
    _db_url = f"postgresql://{_auth}{_url_host}:{_port}/{_encoded_name}"

if _db_url.startswith("postgresql://") and "+" not in _db_url.split("://", 1)[0]:
    _db_url = _db_url.replace("postgresql://", "postgresql+psycopg://", 1)

config.set_main_option("sqlalchemy.url", _db_url.replace("%", "%%"))

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
