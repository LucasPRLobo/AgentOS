"""JWT + API key authentication middleware for FastAPI dashboard."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import uuid
from base64 import urlsafe_b64decode, urlsafe_b64encode
from pathlib import Path

from agentos.schemas.auth import APIKey, AuthConfig, Role, User


class AuthManager:
    """Manages users, API keys, and JWT tokens.

    Authentication is optional — disabled by default for local-first usage.
    When enabled, provides JWT for dashboard and API keys for programmatic access.
    """

    def __init__(self, config: AuthConfig, db_path: str = ":memory:") -> None:
        self._config = config
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'operator',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(user_id),
                name TEXT NOT NULL,
                key_hash TEXT NOT NULL,
                prefix TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'operator',
                created_at TEXT NOT NULL,
                expires_at TEXT
            );
        """)
        self._conn.commit()

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    def create_user(self, username: str, password: str, role: Role = Role.OPERATOR) -> User:
        """Create a new user. Returns the User object."""
        user_id = str(uuid.uuid4())
        password_hash = self._hash_password(password)
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            self._conn.execute(
                "INSERT INTO users (user_id, username, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, password_hash, role.value, now),
            )
            self._conn.commit()
        return User(user_id=user_id, username=username, role=role)

    def authenticate(self, username: str, password: str) -> User | None:
        """Authenticate a user by username and password."""
        with self._lock:
            row = self._conn.execute(
                "SELECT user_id, username, password_hash, role FROM users WHERE username = ?",
                (username,),
            ).fetchone()
        if row is None:
            return None
        if not self._verify_password(password, row[2]):
            return None
        return User(user_id=row[0], username=row[1], role=Role(row[3]))

    def create_jwt(self, user: User) -> str:
        """Create a JWT token for a user."""
        header = urlsafe_b64encode(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()).decode().rstrip("=")
        payload_data = {
            "sub": user.user_id,
            "username": user.username,
            "role": user.role.value,
            "exp": int(time.time()) + self._config.token_expiry_hours * 3600,
        }
        payload = urlsafe_b64encode(json.dumps(payload_data).encode()).decode().rstrip("=")
        signature = self._sign(f"{header}.{payload}")
        return f"{header}.{payload}.{signature}"

    def verify_jwt(self, token: str) -> User | None:
        """Verify a JWT token and return the User, or None if invalid."""
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None
            header_b64, payload_b64, signature = parts
            if not self._verify_signature(f"{header_b64}.{payload_b64}", signature):
                return None
            # Add padding
            payload_b64 += "=" * (4 - len(payload_b64) % 4)
            payload_data = json.loads(urlsafe_b64decode(payload_b64))
            if payload_data.get("exp", 0) < time.time():
                return None
            return User(
                user_id=payload_data["sub"],
                username=payload_data["username"],
                role=Role(payload_data["role"]),
            )
        except Exception:
            return None

    def create_api_key(self, user_id: str, name: str, role: Role = Role.OPERATOR) -> tuple[str, APIKey]:
        """Create an API key. Returns (raw_key, APIKey)."""
        raw_key = secrets.token_urlsafe(32)
        key_id = str(uuid.uuid4())
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        prefix = raw_key[:8]
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        with self._lock:
            self._conn.execute(
                "INSERT INTO api_keys (key_id, user_id, name, key_hash, prefix, role, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key_id, user_id, name, key_hash, prefix, role.value, now),
            )
            self._conn.commit()
        api_key = APIKey(key_id=key_id, user_id=user_id, name=name, prefix=prefix, role=role)
        return raw_key, api_key

    def verify_api_key(self, raw_key: str) -> User | None:
        """Verify an API key and return the associated User."""
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
        with self._lock:
            row = self._conn.execute(
                """SELECT ak.user_id, u.username, ak.role FROM api_keys ak
                   JOIN users u ON ak.user_id = u.user_id
                   WHERE ak.key_hash = ?""",
                (key_hash,),
            ).fetchone()
        if row is None:
            return None
        return User(user_id=row[0], username=row[1], role=Role(row[2]))

    def revoke_api_key(self, key_id: str) -> bool:
        """Revoke an API key. Returns True if found and revoked."""
        with self._lock:
            cursor = self._conn.execute("DELETE FROM api_keys WHERE key_id = ?", (key_id,))
            self._conn.commit()
            return cursor.rowcount > 0

    def list_api_keys(self, user_id: str) -> list[APIKey]:
        """List all API keys for a user."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT key_id, user_id, name, prefix, role, created_at FROM api_keys WHERE user_id = ?",
                (user_id,),
            ).fetchall()
        return [
            APIKey(key_id=r[0], user_id=r[1], name=r[2], prefix=r[3], role=Role(r[4]))
            for r in rows
        ]

    def has_permission(self, user: User, action: str) -> bool:
        """Check if a user has permission for an action."""
        permissions = {
            Role.VIEWER: {"read"},
            Role.OPERATOR: {"read", "run", "gate"},
            Role.ADMIN: {"read", "run", "gate", "manage_users", "manage_keys"},
        }
        return action in permissions.get(user.role, set())

    @staticmethod
    def _hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        h = hashlib.sha256(f"{salt}:{password}".encode()).hexdigest()
        return f"{salt}:{h}"

    @staticmethod
    def _verify_password(password: str, stored_hash: str) -> bool:
        salt, h = stored_hash.split(":", 1)
        return hashlib.sha256(f"{salt}:{password}".encode()).hexdigest() == h

    def _sign(self, data: str) -> str:
        return hmac.new(
            self._config.jwt_secret.encode(),
            data.encode(),
            hashlib.sha256,
        ).hexdigest()

    def _verify_signature(self, data: str, signature: str) -> bool:
        expected = self._sign(data)
        return hmac.compare_digest(expected, signature)
