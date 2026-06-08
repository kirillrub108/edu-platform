"""Unit tests for one-time email-verification tokens + resend cooldown."""

from __future__ import annotations

import uuid

import fakeredis.aioredis
import pytest

from app.services import auth_service, email_token_service
from app.services.email_token_service import TokenError

pytestmark = pytest.mark.unit


def _redis() -> fakeredis.aioredis.FakeRedis:
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


async def test_consume_valid_token_returns_user_id() -> None:
    user_id = str(uuid.uuid4())
    redis = _redis()
    token = email_token_service.issue(user_id)
    assert await email_token_service.consume(redis, token) == user_id


async def test_consume_is_one_time() -> None:
    user_id = str(uuid.uuid4())
    redis = _redis()
    token = email_token_service.issue(user_id)

    assert await email_token_service.consume(redis, token) == user_id
    with pytest.raises(TokenError) as exc:
        await email_token_service.consume(redis, token)
    assert exc.value.reason == "used"


async def test_consume_expired_token(monkeypatch: pytest.MonkeyPatch) -> None:
    user_id = str(uuid.uuid4())
    redis = _redis()
    token = email_token_service.issue(user_id)
    monkeypatch.setattr(auth_service, "EMAIL_VERIFICATION_TTL_SECONDS", -1)
    with pytest.raises(TokenError) as exc:
        await email_token_service.consume(redis, token)
    assert exc.value.reason == "expired"


async def test_consume_invalid_token() -> None:
    redis = _redis()
    with pytest.raises(TokenError) as exc:
        await email_token_service.consume(redis, "not-a-real-token")
    assert exc.value.reason == "invalid"


async def test_cooldown_roundtrip() -> None:
    user_id = str(uuid.uuid4())
    redis = _redis()
    assert await email_token_service.under_cooldown(redis, user_id) is False
    await email_token_service.start_cooldown(redis, user_id)
    assert await email_token_service.under_cooldown(redis, user_id) is True
