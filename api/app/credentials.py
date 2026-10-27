"""Durable operator credentials; legacy plaintext files remain usable unchanged."""
import hashlib
import hmac
import os
import secrets
import tempfile
from pathlib import Path
from contextlib import contextmanager
import fcntl


def demo_mode():
    return os.getenv("OMNIFLOW_DEMO", "false").lower() == "true"


def credential_path():
    return Path(os.getenv("OPERATOR_PASSWORD_FILE", "/run/omniflow-api/operator_password"))


def read_credential():
    path = credential_path()
    if path.exists():
        value = path.read_text().rstrip("\r\n")
        if not value:
            raise RuntimeError("Stored operator credential is empty; use explicit recovery")
        return value
    return os.getenv("OPERATOR_PASSWORD", "")


def fingerprint(value=None):
    return hashlib.sha256((read_credential() if value is None else value).encode()).digest()


def verify(password, value=None):
    value = read_credential() if value is None else value
    if not value:
        return False
    if value.startswith("pbkdf2_sha256$"):
        _, iterations, salt, expected = value.split("$")
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(actual, expected)
    return hmac.compare_digest(password.encode(), value.encode())


@contextmanager
def credential_lock():
    path = credential_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / ".operator.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield


def set_password(password, *, reset=False):
    if len(password) < 16 or len(password) > 512 or not password.strip():
        raise ValueError("Use a password between 16 and 512 characters")
    with credential_lock():
        if not reset and read_credential():
            raise FileExistsError("Operator is already configured")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600000).hex()
        path = credential_path()
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".operator-")
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(f"pbkdf2_sha256$600000${salt.hex()}${digest}\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)


if __name__ == "__main__":
    import getpass
    import argparse
    parser = argparse.ArgumentParser(description="Explicitly reset the persisted operator password")
    parser.add_argument("--reset", action="store_true", required=True)
    parser.parse_args()
    password = getpass.getpass("New password (16+ characters): ")
    if password != getpass.getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    set_password(password, reset=True)
    print("Password reset. Existing sessions are invalidated.")
