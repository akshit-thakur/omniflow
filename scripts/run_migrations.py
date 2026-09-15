"""Compose entrypoint: reconcile access, then apply Alembic migrations.

PostgreSQL's container entrypoint consumes ``POSTGRES_*`` only when the data
directory is empty. A persisted volume can therefore be healthy while a changed
login, password, or database name makes every application connection fail. This
runner first retries the configured connection and, when explicitly given a
trusted local PostgreSQL socket, can repair that narrow configuration drift
without deleting or replacing an existing database.
"""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
from urllib.parse import quote

from sqlalchemy import create_engine, text


_AUTHENTICATION_SQLSTATES = {"28000", "28P01"}
_MISSING_DATABASE_SQLSTATE = "3D000"


class DatabaseTarget:
    __slots__ = ("url", "user", "password", "host", "port", "name")

    def __init__(
        self,
        *,
        url: str,
        user: str,
        password: str,
        host: str | None,
        port: int,
        name: str,
    ) -> None:
        self.url = url
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.name = name


def _configured_password_file() -> str | None:
    configured = [
        (name, value)
        for name in (
            "DATABASE_PASSWORD_FILE",
            "DB_PASSWORD_FILE",
            "POSTGRES_PASSWORD_FILE",
        )
        if (value := os.getenv(name))
    ]
    if not configured:
        return None
    paths = {value for _, value in configured}
    if len(paths) != 1:
        names = ", ".join(name for name, _ in configured)
        raise RuntimeError(f"Conflicting database password files: {names}")
    direct = [
        name
        for name in ("DATABASE_PASSWORD", "DB_PASSWORD", "POSTGRES_PASSWORD")
        if os.getenv(name) is not None
    ]
    if direct:
        raise RuntimeError(
            "Set a database password value or a *_PASSWORD_FILE, not both "
            f"({', '.join(direct)} conflicts with {configured[0][0]})"
        )
    return configured[0][1]


def _read_password_file(path: str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeError(f"Cannot read database password file {path!r}: {exc}") from exc
    if value.endswith("\r\n"):
        value = value[:-2]
    elif value.endswith("\n"):
        value = value[:-1]
    if not value:
        raise RuntimeError(f"Database password file {path!r} is empty")
    if "\x00" in value or "\n" in value or "\r" in value:
        raise RuntimeError("Database password files must contain exactly one line")
    return value


def _normalize_driver(database_url: str) -> str:
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def build_database_url() -> str:
    password_file = _configured_password_file()
    file_password = _read_password_file(password_file) if password_file else None
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        normalized = _normalize_driver(database_url)
        if file_password is None:
            return normalized
        # Import lazily so the lightweight mocked migration tests need only the
        # top-level create_engine/text API.
        from sqlalchemy.engine import make_url

        parsed = make_url(normalized)
        if parsed.password is not None:
            raise RuntimeError(
                "DATABASE_URL already contains a password and cannot be combined "
                "with a database password file"
            )
        return parsed.set(password=file_password).render_as_string(hide_password=False)

    user = os.getenv("DATABASE_USER") or os.getenv("DB_USER", "postgres")
    password = file_password
    if password is None:
        password = os.getenv("DATABASE_PASSWORD") or os.getenv("DB_PASSWORD") or os.getenv("POSTGRES_PASSWORD")
        if not password or not password.strip():
            raise RuntimeError("A database password or password file is required")
    host = os.getenv("DATABASE_HOST") or os.getenv("DB_HOST", "localhost")
    port = os.getenv("DATABASE_PORT") or os.getenv("DB_PORT", "5432")
    name = os.getenv("DATABASE_NAME") or os.getenv("DB_NAME", "omniflow")

    encoded_user = quote(user, safe="")
    encoded_name = quote(name, safe="")
    url_host = host
    if ":" in url_host and not (url_host.startswith("[") and url_host.endswith("]")):
        url_host = f"[{url_host}]"
    auth = f"{encoded_user}:{quote(password, safe='')}@" if password else f"{encoded_user}@"
    return f"postgresql+psycopg://{auth}{url_host}:{port}/{encoded_name}"


def _database_target(
    database_url: str, *, require_password: bool = True
) -> DatabaseTarget:
    parsed = make_url(database_url)
    if parsed.get_backend_name() != "postgresql":
        raise RuntimeError("Database reconciliation supports PostgreSQL URLs only")
    if not parsed.username:
        raise RuntimeError("The configured database URL has no username")
    if not parsed.database:
        raise RuntimeError("The configured database URL has no database name")
    password = parsed.password or ""
    if require_password and not password:
        raise RuntimeError("The configured database password is empty")
    return DatabaseTarget(
        url=database_url,
        user=parsed.username,
        password=password,
        host=parsed.host,
        port=parsed.port or 5432,
        name=parsed.database,
    )


def _bounded_number(name: str, default: float, *, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be numeric") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} must be between {minimum:g} and {maximum:g}")
    return value


def _sqlstate(exc: Exception) -> str | None:
    original = getattr(exc, "orig", exc)
    diagnostic = getattr(original, "diag", None)
    return (
        getattr(original, "sqlstate", None)
        or getattr(original, "pgcode", None)
        or getattr(diagnostic, "sqlstate", None)
    )


def _connection_error_category(exc: Exception) -> str | None:
    state = _sqlstate(exc)
    if state in _AUTHENTICATION_SQLSTATES:
        return "authentication"
    if state == _MISSING_DATABASE_SQLSTATE:
        return "missing_database"

    # Psycopg deliberately exposes no SQLSTATE for some startup/authentication
    # failures. Match only PostgreSQL's stable, narrow FATAL messages; never
    # echo the connection error because its rendered URL may contain a secret.
    original = getattr(exc, "orig", exc)
    message = str(original).lower()
    if (
        "password authentication failed" in message
        or "no password supplied" in message
        or ("role \"" in message and "does not exist" in message)
    ):
        return "authentication"
    if "database \"" in message and "does not exist" in message:
        return "missing_database"
    return None


def wait_for_database(engine) -> Exception | None:
    attempts = int(
        _bounded_number("DATABASE_CONNECT_ATTEMPTS", 30, minimum=1, maximum=60)
    )
    delay = _bounded_number(
        "DATABASE_CONNECT_RETRY_SECONDS", 1, minimum=0, maximum=30
    )
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1")).scalar_one()
            return None
        except Exception as exc:  # SQLAlchemy wraps driver connection failures.
            last_error = exc
            if _connection_error_category(exc) is not None:
                break
            if attempt < attempts:
                print(
                    f"Database is not ready (attempt {attempt}/{attempts}); retrying",
                    flush=True,
                )
                time.sleep(delay)
    return last_error


def _trusted_socket(port: int) -> str:
    socket_directory = os.getenv("DATABASE_ADMIN_SOCKET")
    if not socket_directory:
        raise RuntimeError(
            "The configured database connection failed and no trusted local "
            "reconciliation socket is enabled. Existing PostgreSQL volumes do "
            "not apply changed POSTGRES_USER, POSTGRES_DB, or POSTGRES_PASSWORD "
            "values; restore the volume's original values or mount its local "
            "socket into database-init and set DATABASE_ADMIN_SOCKET."
        )
    if not os.path.isabs(socket_directory):
        raise RuntimeError("DATABASE_ADMIN_SOCKET must be an absolute directory")
    socket_path = os.path.join(socket_directory, f".s.PGSQL.{port}")
    try:
        mode = os.stat(socket_path).st_mode
    except OSError as exc:
        raise RuntimeError(
            f"Trusted PostgreSQL socket {socket_path!r} is unavailable: {exc}"
        ) from exc
    if not stat.S_ISSOCK(mode):
        raise RuntimeError(f"Trusted PostgreSQL socket {socket_path!r} is not a socket")
    return socket_directory


def _socket_url(socket_directory: str, port: int, user: str, database: str) -> str:
    return (
        f"postgresql+psycopg://{quote(user, safe='')}@/"
        f"{quote(database, safe='')}?host={quote(socket_directory, safe='')}&port={port}"
    )


def _admin_users(target_user: str) -> list[str]:
    candidates: list[str] = []
    for name in ("DATABASE_ADMIN_USER", "DATABASE_LEGACY_SUPERUSER"):
        value = os.getenv(name)
        if value:
            candidates.extend(item.strip() for item in value.split(","))
    candidates.extend((target_user, "omniflow", "postgres"))
    return list(dict.fromkeys(item for item in candidates if item))


def _admin_databases(target_database: str) -> list[str]:
    configured = os.getenv("DATABASE_ADMIN_DATABASE")
    return list(
        dict.fromkeys(
            item for item in (configured, "postgres", target_database, "template1") if item
        )
    )


def _find_trusted_admin(
    socket_directory: str, target: DatabaseTarget
) -> tuple[str, str]:
    rejected_non_superusers: list[str] = []
    for user in _admin_users(target.user):
        for database in _admin_databases(target.name):
            engine = create_engine(_socket_url(socket_directory, target.port, user, database))
            try:
                with engine.connect() as conn:
                    row = conn.execute(
                        text(
                            "SELECT current_user, rolsuper "
                            "FROM pg_roles WHERE rolname = current_user"
                        )
                    ).first()
                if row and bool(row[1]):
                    return str(row[0]), database
                if row:
                    rejected_non_superusers.append(str(row[0]))
            except Exception:
                # Local trust still rejects a role or database that does not exist.
                pass
            finally:
                engine.dispose()
    suffix = ""
    if rejected_non_superusers:
        suffix = "; non-superuser candidates: " + ", ".join(
            sorted(set(rejected_non_superusers))
        )
    raise RuntimeError(
        "No known PostgreSQL superuser could connect through the trusted local "
        "socket. Set DATABASE_ADMIN_USER to the role that initialized this volume"
        + suffix
    )


def _format_and_execute(conn, format_sql: str, parameters: dict[str, str]) -> None:
    try:
        command = conn.execute(text(format_sql), parameters).scalar_one()
        conn.exec_driver_sql(command)
    except Exception:
        # The formatted command can contain a password literal. Never attach the
        # driver exception (and its rendered SQL) to the public traceback.
        raise RuntimeError("PostgreSQL reconciliation DDL failed") from None


def reconcile_database(database_url: str, connection_error: Exception) -> None:
    """Repair only explicit, non-destructive persisted-volume configuration drift."""
    target = _database_target(database_url)
    socket_directory = _trusted_socket(target.port)
    admin_user, admin_database = _find_trusted_admin(socket_directory, target)
    admin_engine = create_engine(
        _socket_url(socket_directory, target.port, admin_user, admin_database),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with admin_engine.connect() as conn:
            role = conn.execute(
                text(
                    "SELECT rolcanlogin, rolsuper FROM pg_roles WHERE rolname = :role"
                ),
                {"role": target.user},
            ).first()
            database_exists = bool(
                conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :database"),
                    {"database": target.name},
                ).scalar()
            )
        error_category = _connection_error_category(connection_error)
        create_role = role is None
        rotate_password = (
            create_role
            or not bool(role[0])
        )
        create_database = not database_exists
        if not (create_role or rotate_password or create_database):
            raise RuntimeError(
                "The configured role and database already exist, but the network "
                "connection still fails. Refusing to change credentials for a "
                "non-authentication failure. Check DATABASE_HOST, DATABASE_PORT, "
                "DNS, and TLS settings."
            ) from connection_error

        with admin_engine.connect() as conn:
            if create_role:
                _format_and_execute(
                    conn,
                    "SELECT format('CREATE ROLE %I LOGIN SUPERUSER PASSWORD %L', "
                    "CAST(:role AS text), CAST(:password AS text))",
                    {"role": target.user, "password": target.password},
                )
                print(f"Created configured PostgreSQL login {target.user!r}", flush=True)
            if create_database:
                _format_and_execute(
                    conn,
                    "SELECT format('CREATE DATABASE %I OWNER %I', "
                    "CAST(:database AS text), CAST(:role AS text))",
                    {"database": target.name, "role": target.user},
                )
                print(f"Created configured PostgreSQL database {target.name!r}", flush=True)
            if rotate_password and not create_role:
                _format_and_execute(
                    conn,
                    "SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', "
                    "CAST(:role AS text), CAST(:password AS text))",
                    {"role": target.user, "password": target.password},
                )
                print(f"Updated configured PostgreSQL login {target.user!r}", flush=True)
    finally:
        admin_engine.dispose()


def _migration_environment(database_url: str) -> dict[str, str]:
    environment = os.environ.copy()
    # Alembic must receive the effective URL when the password came from a file.
    environment["DATABASE_URL"] = database_url
    return environment


def provision_runtime_roles(database_url: str) -> None:
    """Install installation-specific non-privileged logins before Alembic."""
    from sqlalchemy.engine import make_url

    api_user = os.getenv("DATABASE_RUNTIME_USER", "omniflow_api")
    ai_user = os.getenv("AI_RUNTIME_USER", "omniflow_ai")
    api_file = os.getenv("DATABASE_RUNTIME_PASSWORD_FILE")
    ai_file = os.getenv("AI_RUNTIME_PASSWORD_FILE")
    if not api_file or not ai_file:
        return
    api_password = _read_password_file(api_file)
    ai_password = _read_password_file(ai_file)
    admin_engine = create_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as conn:
            for role, password in ((api_user, api_password), (ai_user, ai_password)):
                create_command = conn.execute(
                    text(
                        """SELECT CASE WHEN EXISTS(
                           SELECT 1 FROM pg_roles WHERE rolname=:role
                         ) THEN NULL ELSE format(
                           'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION PASSWORD %L',
                           CAST(:role AS text), CAST(:password AS text)
                         ) END"""
                    ), {"role": role, "password": password}
                ).scalar()
                if create_command:
                    _format_and_execute(
                        conn,
                        "SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION PASSWORD %L', CAST(:role AS text), CAST(:password AS text))",
                        {"role": role, "password": password},
                    )
                _format_and_execute(
                    conn,
                    "SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION PASSWORD %L', CAST(:role AS text), CAST(:password AS text))",
                    {"role": role, "password": password},
                )
                owned, member = conn.execute(
                    text(
                        """SELECT EXISTS(
                           SELECT 1 FROM pg_class c JOIN pg_roles r ON r.oid=c.relowner
                           WHERE r.rolname=:role AND c.relnamespace='public'::regnamespace
                         ), EXISTS(
                           SELECT 1 FROM pg_auth_members m JOIN pg_roles r ON r.oid=m.member
                           WHERE r.rolname=:role
                         )"""
                    ), {"role": role}
                ).one()
                if owned or member:
                    raise RuntimeError(f"Runtime role {role!r} owns objects or has role membership")
    finally:
        admin_engine.dispose()


@contextmanager
def _migration_lock():
    lock_path = os.getenv("DATABASE_MIGRATION_LOCK_FILE")
    if not lock_path:
        yield
        return
    if not os.path.isabs(lock_path):
        raise RuntimeError("DATABASE_MIGRATION_LOCK_FILE must be an absolute path")
    try:
        import fcntl
    except ImportError as exc:
        raise RuntimeError(
            "DATABASE_MIGRATION_LOCK_FILE requires POSIX file locking support"
        ) from exc

    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise RuntimeError(f"Cannot open migration lock file {lock_path!r}: {exc}") from exc
    with os.fdopen(descriptor, "a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _run_migrations() -> int:
    database_url = build_database_url()
    engine = create_engine(database_url)
    connection_error = wait_for_database(engine)
    if connection_error is not None:
        engine.dispose()
        reconcile_database(database_url, connection_error)
        engine = create_engine(database_url)
        connection_error = wait_for_database(engine)
        if connection_error is not None:
            engine.dispose()
            raise RuntimeError(
                "Database reconciliation completed, but the configured connection "
                "still fails"
            ) from connection_error

    engine.dispose()

    provision_runtime_roles(database_url)

    subprocess.check_call(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        env=_migration_environment(database_url),
    )
    return 0


def main() -> int:
    with _migration_lock():
        return _run_migrations()


if __name__ == "__main__":
    raise SystemExit(main())
