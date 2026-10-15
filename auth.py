import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from collections import deque
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Generator
from uuid import uuid4


_DUMMY_SALT = bytes.fromhex("ef94d6c4a0b13c12a54219c247eea001")
_DUMMY_HASH = hashlib.scrypt(
    b"not-a-real-password",
    salt=_DUMMY_SALT,
    n=2**14,
    r=8,
    p=1,
    dklen=32,
)
SESSION_COOKIE_NAME = "trustrag_session"
SESSION_MAX_AGE_SECONDS = 7 * 24 * 60 * 60


class AccountExistsError(ValueError):
    pass


class AuthenticationError(ValueError):
    pass


class AuthStore:
    def __init__(
        self,
        database_path: str | Path,
        secret_key: str | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._secret_key = (
            secret_key
            or os.getenv("TRUSTRAG_SECRET_KEY")
            or secrets.token_urlsafe(48)
        ).encode("utf-8")
        self._initialize_database()

    @contextmanager
    def _connection(
        self,
    ) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize_database(self) -> None:
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    expires_at INTEGER NOT NULL
                )
                """
            )

    @staticmethod
    def _password_hash(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=2**14,
            r=8,
            p=1,
            dklen=32,
        )

    def register(self, email: str, password: str) -> dict[str, str]:
        normalized_email = email.strip().casefold()
        user_id = uuid4().hex
        created_at = datetime.now(UTC).isoformat()
        salt = secrets.token_bytes(16)
        password_hash = self._password_hash(password, salt)

        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO users (id, email, password_salt, password_hash, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (user_id, normalized_email, salt, password_hash, created_at),
                )
        except sqlite3.IntegrityError as error:
            raise AccountExistsError(
                "An account with this email already exists."
            ) from error

        return {"id": user_id, "email": normalized_email, "created_at": created_at}

    def authenticate(self, email: str, password: str) -> dict[str, str]:
        normalized_email = email.strip().casefold()
        with self._connection() as connection:
            user = connection.execute(
                """
                SELECT id, email, password_salt, password_hash, created_at
                FROM users WHERE email = ?
                """,
                (normalized_email,),
            ).fetchone()

        if user is None:
            candidate_hash = self._password_hash(password, _DUMMY_SALT)
            hmac.compare_digest(candidate_hash, _DUMMY_HASH)
            raise AuthenticationError("Email or password is incorrect.")

        candidate_hash = self._password_hash(password, user["password_salt"])
        if not hmac.compare_digest(candidate_hash, user["password_hash"]):
            raise AuthenticationError("Email or password is incorrect.")

        return {
            "id": user["id"],
            "email": user["email"],
            "created_at": user["created_at"],
        }

    @staticmethod
    def _encode(value: bytes) -> str:
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    def create_session(self, user_id: str) -> str:
        session_id = uuid4().hex
        expires_at = int(time.time()) + SESSION_MAX_AGE_SECONDS
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)",
                (session_id, user_id, expires_at),
            )
        payload = json.dumps({
            "sid": session_id,
            "exp": expires_at,
        }, separators=(",", ":")).encode("utf-8")
        encoded_payload = self._encode(payload)
        signature = hmac.new(
            self._secret_key,
            encoded_payload.encode("ascii"),
            hashlib.sha256,
        ).digest()
        return f"{encoded_payload}.{self._encode(signature)}"

    @staticmethod
    def _decode(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def get_user_from_session(self, token: str) -> dict[str, str] | None:
        try:
            encoded_payload, encoded_signature = token.split(".", maxsplit=1)
            signature = self._decode(encoded_signature)
            expected_signature = hmac.new(
                self._secret_key,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected_signature):
                return None

            payload = json.loads(self._decode(encoded_payload))
            if not isinstance(payload, dict) or payload.get("exp", 0) <= time.time():
                return None
            session_id = payload.get("sid")
            if not isinstance(session_id, str):
                return None
        except (ValueError, TypeError, json.JSONDecodeError):
            return None

        with self._connection() as connection:
            user = connection.execute(
                """
                SELECT users.id, users.email, users.created_at
                FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE sessions.id = ? AND sessions.expires_at > ?
                """,
                (session_id, int(time.time())),
            ).fetchone()
        return dict(user) if user is not None else None

    def revoke_session(self, token: str | None) -> None:
        if not token:
            return
        try:
            encoded_payload, encoded_signature = token.split(".", maxsplit=1)
            signature = self._decode(encoded_signature)
            expected_signature = hmac.new(
                self._secret_key,
                encoded_payload.encode("ascii"),
                hashlib.sha256,
            ).digest()
            if not hmac.compare_digest(signature, expected_signature):
                return
            payload = json.loads(self._decode(encoded_payload))
            session_id = payload.get("sid") if isinstance(payload, dict) else None
            if not isinstance(session_id, str):
                return
        except (ValueError, TypeError, json.JSONDecodeError):
            return

        with self._connection() as connection:
            connection.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def delete_account(self, user_id: str) -> bool:
        with self._connection() as connection:
            tables = {
                row["name"]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            if "documents" in tables:
                document_columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(documents)"
                    ).fetchall()
                }
                if "user_id" in document_columns:
                    connection.execute(
                        "DELETE FROM documents WHERE user_id = ?",
                        (user_id,),
                    )
            cursor = connection.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return cursor.rowcount > 0


class AuthRateLimiter:
    def __init__(
        self,
        attempts: int = 10,
        window_seconds: int = 900,
        max_clients: int = 4096,
    ) -> None:
        self.attempts = attempts
        self.window_seconds = window_seconds
        self.max_clients = max_clients
        self._requests: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            history = self._requests.get(key)
            if history is None:
                if len(self._requests) >= self.max_clients:
                    expired_keys = [
                        client_key
                        for client_key, requests in self._requests.items()
                        if not requests
                        or now - requests[-1] >= self.window_seconds
                    ]
                    for client_key in expired_keys:
                        del self._requests[client_key]
                    if len(self._requests) >= self.max_clients:
                        return False
                history = self._requests.setdefault(key, deque())
            while history and now - history[0] >= self.window_seconds:
                history.popleft()
            if len(history) >= self.attempts:
                return False
            history.append(now)
            return True
