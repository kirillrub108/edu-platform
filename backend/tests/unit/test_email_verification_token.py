"""Unit tests for the stateless email-verification token helpers."""

from __future__ import annotations

import uuid

import pytest

from app.services import auth_service
from app.services.auth_service import (
    generate_email_verification_token,
    verify_email_verification_token,
)

pytestmark = pytest.mark.unit


def test_valid_token_roundtrips_user_id() -> None:
    user_id = str(uuid.uuid4())
    token = generate_email_verification_token(user_id)
    assert verify_email_verification_token(token) == user_id


def test_expired_token_raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = str(uuid.uuid4())
    token = generate_email_verification_token(user_id)
    # Force every issued token to be considered expired.
    monkeypatch.setattr(auth_service, "EMAIL_VERIFICATION_TTL_SECONDS", -1)
    with pytest.raises(ValueError) as exc:
        verify_email_verification_token(token)
    assert str(exc.value) == "expired"


def test_tampered_token_raises_value_error() -> None:
    user_id = str(uuid.uuid4())
    token = generate_email_verification_token(user_id)
    tampered = token[:-2] + ("AA" if token[-2:] != "AA" else "BB")
    with pytest.raises(ValueError) as exc:
        verify_email_verification_token(tampered)
    assert str(exc.value) == "invalid"


def test_token_from_different_salt_is_rejected() -> None:
    # A token signed with the same key but a different salt must not validate —
    # guards against cross-purpose token reuse.
    from itsdangerous import URLSafeTimedSerializer

    from app.config import settings

    foreign = URLSafeTimedSerializer(settings.SECRET_KEY, salt="other-salt").dumps("x")
    with pytest.raises(ValueError):
        verify_email_verification_token(foreign)
