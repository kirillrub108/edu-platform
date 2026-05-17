"""Unit tests for app.services.auth_service — pure functions only.

The full AuthService.register/login/refresh flow is exercised via the
HTTP routes in tests/integration/test_auth_routes.py; here we cover the
low-level primitives.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from freezegun import freeze_time

from app.config import settings
from app.models.user import UserRole
from app.services.auth_service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

pytestmark = pytest.mark.unit


def _fake_user(role: UserRole = UserRole.teacher):
    return SimpleNamespace(
        id=uuid.uuid4(),
        email="alice@example.com",
        role=role,
    )


@pytest.mark.parametrize(
    "password",
    ["short", "password123", "со-юникодом!", "  spaces around  "],
)
def test_hash_and_verify_password_roundtrip(password: str) -> None:
    hashed = hash_password(password)
    assert hashed != password
    assert verify_password(password, hashed) is True


def test_verify_password_with_wrong_password_returns_false() -> None:
    hashed = hash_password("correct-horse-battery-staple")
    assert verify_password("nope", hashed) is False


def test_create_access_token_payload_shape() -> None:
    user = _fake_user(UserRole.teacher)
    token, jti, exp = create_access_token(user)

    decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert decoded["sub"] == str(user.id)
    assert decoded["type"] == "access"
    assert decoded["role"] == "teacher"
    assert decoded["jti"] == jti
    assert decoded["exp"] == int(exp.timestamp())
    assert exp > datetime.now(timezone.utc)


def test_create_refresh_token_has_refresh_type_and_family() -> None:
    family = str(uuid.uuid4())
    absolute = datetime.now(timezone.utc) + timedelta(days=14)
    token, jti, _exp = create_refresh_token(
        "user-id-x", family, sliding_days=14, absolute_expires_at=absolute
    )
    decoded = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert decoded["type"] == "refresh"
    assert decoded["family_id"] == family
    assert decoded["jti"] == jti
    assert decoded["sub"] == "user-id-x"


def test_decode_token_with_expired_exp_raises_401() -> None:
    """Mint a token in the past so it is already expired at decode time."""
    user = _fake_user()
    with freeze_time(datetime(2020, 1, 1, tzinfo=timezone.utc)):
        token, _, _ = create_access_token(user)

    # Default freeze is gone — token is now ~years past its exp.
    with pytest.raises(HTTPException) as exc:
        decode_token(token)
    assert exc.value.status_code == 401
    assert "expired" in exc.value.detail.lower()


def test_decode_token_signed_with_other_secret_raises_401() -> None:
    payload = {
        "sub": "user-id",
        "type": "access",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
    }
    bad_token = jwt.encode(payload, "different-secret", algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(HTTPException) as exc:
        decode_token(bad_token)
    assert exc.value.status_code == 401


def test_decode_token_with_verify_exp_false_accepts_expired() -> None:
    user = _fake_user()
    with freeze_time(datetime(2020, 1, 1, tzinfo=timezone.utc)):
        token, _, _ = create_access_token(user)

    payload = decode_token(token, verify_exp=False)
    assert payload["sub"] == str(user.id)
