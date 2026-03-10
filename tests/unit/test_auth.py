"""Tests for authentication and multi-user support."""

from __future__ import annotations

import pytest

from agentos.dashboard.auth import AuthManager
from agentos.schemas.auth import APIKey, AuthConfig, Role, User


@pytest.fixture
def auth_config() -> AuthConfig:
    return AuthConfig(enabled=True, jwt_secret="test-secret-key-for-testing", token_expiry_hours=1)


@pytest.fixture
def auth(auth_config) -> AuthManager:
    return AuthManager(auth_config)


class TestAuthDisabledDefault:
    def test_default_disabled(self):
        config = AuthConfig()
        assert config.enabled is False
        assert config.allow_anonymous is True

    def test_auth_manager_disabled(self):
        mgr = AuthManager(AuthConfig())
        assert mgr.enabled is False


class TestUserCreation:
    def test_create_user(self, auth):
        user = auth.create_user("alice", "password123")
        assert user.username == "alice"
        assert user.role == Role.OPERATOR
        assert user.user_id

    def test_create_admin(self, auth):
        user = auth.create_user("admin", "admin_pass", Role.ADMIN)
        assert user.role == Role.ADMIN


class TestAuthentication:
    def test_valid_credentials(self, auth):
        auth.create_user("alice", "password123")
        user = auth.authenticate("alice", "password123")
        assert user is not None
        assert user.username == "alice"

    def test_wrong_password(self, auth):
        auth.create_user("alice", "password123")
        user = auth.authenticate("alice", "wrong_password")
        assert user is None

    def test_nonexistent_user(self, auth):
        user = auth.authenticate("nobody", "password")
        assert user is None


class TestJWT:
    def test_create_and_verify_jwt(self, auth):
        user = auth.create_user("alice", "pass")
        token = auth.create_jwt(user)
        verified = auth.verify_jwt(token)
        assert verified is not None
        assert verified.username == "alice"
        assert verified.user_id == user.user_id

    def test_invalid_token(self, auth):
        assert auth.verify_jwt("invalid.token.here") is None

    def test_tampered_token(self, auth):
        user = auth.create_user("alice", "pass")
        token = auth.create_jwt(user)
        parts = token.split(".")
        parts[1] = parts[1] + "tampered"
        tampered = ".".join(parts)
        assert auth.verify_jwt(tampered) is None

    def test_expired_token(self):
        config = AuthConfig(enabled=True, jwt_secret="secret", token_expiry_hours=0)
        mgr = AuthManager(config)
        user = mgr.create_user("alice", "pass")
        token = mgr.create_jwt(user)
        # Token expires immediately (0 hours)
        import time
        time.sleep(0.1)
        assert mgr.verify_jwt(token) is None


class TestAPIKeys:
    def test_create_and_verify_api_key(self, auth):
        user = auth.create_user("alice", "pass")
        raw_key, api_key = auth.create_api_key(user.user_id, "test-key")
        assert api_key.name == "test-key"
        assert api_key.prefix == raw_key[:8]

        verified = auth.verify_api_key(raw_key)
        assert verified is not None
        assert verified.username == "alice"

    def test_invalid_api_key(self, auth):
        assert auth.verify_api_key("invalid-key") is None

    def test_revoke_api_key(self, auth):
        user = auth.create_user("alice", "pass")
        raw_key, api_key = auth.create_api_key(user.user_id, "test-key")
        assert auth.revoke_api_key(api_key.key_id) is True
        assert auth.verify_api_key(raw_key) is None

    def test_list_api_keys(self, auth):
        user = auth.create_user("alice", "pass")
        auth.create_api_key(user.user_id, "key-1")
        auth.create_api_key(user.user_id, "key-2")
        keys = auth.list_api_keys(user.user_id)
        assert len(keys) == 2
        names = {k.name for k in keys}
        assert names == {"key-1", "key-2"}


class TestRBAC:
    def test_admin_permissions(self, auth):
        user = User(user_id="u1", username="admin", role=Role.ADMIN)
        assert auth.has_permission(user, "read")
        assert auth.has_permission(user, "run")
        assert auth.has_permission(user, "gate")
        assert auth.has_permission(user, "manage_users")

    def test_operator_permissions(self, auth):
        user = User(user_id="u1", username="op", role=Role.OPERATOR)
        assert auth.has_permission(user, "read")
        assert auth.has_permission(user, "run")
        assert auth.has_permission(user, "gate")
        assert not auth.has_permission(user, "manage_users")

    def test_viewer_permissions(self, auth):
        user = User(user_id="u1", username="viewer", role=Role.VIEWER)
        assert auth.has_permission(user, "read")
        assert not auth.has_permission(user, "run")
        assert not auth.has_permission(user, "gate")
        assert not auth.has_permission(user, "manage_users")


class TestSchemaRoundTrip:
    def test_user_serialization(self):
        user = User(user_id="u1", username="alice", role=Role.OPERATOR)
        data = user.model_dump(mode="json")
        restored = User.model_validate(data)
        assert restored.username == "alice"
        assert restored.role == Role.OPERATOR

    def test_api_key_serialization(self):
        key = APIKey(key_id="k1", user_id="u1", name="test", prefix="abcdefgh")
        data = key.model_dump(mode="json")
        restored = APIKey.model_validate(data)
        assert restored.name == "test"

    def test_auth_config_serialization(self):
        config = AuthConfig(enabled=True, jwt_secret="secret", token_expiry_hours=48)
        data = config.model_dump(mode="json")
        restored = AuthConfig.model_validate(data)
        assert restored.enabled is True
        assert restored.token_expiry_hours == 48
