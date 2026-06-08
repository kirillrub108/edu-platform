"""POST /auth/verify-email (one-time) + the require_verified_email AI gate."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.models.user import User, UserRole
from app.services import email_token_service
from app.services.auth_service import create_access_token, hash_password

pytestmark = pytest.mark.integration

# A real lesson is not needed: require_verified_email is declared before
# get_owned_lesson on the quiz-generate endpoint, so the 403 fires for any
# (even non-existent) lesson id before ownership is ever checked.
_QUIZ_GENERATE = f"/api/v1/lessons/{uuid.uuid4()}/quiz/generate"


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


async def _make_unverified_teacher(db: Any) -> User:
    user = User(
        email=_email(),
        hashed_password=hash_password("password123"),
        full_name="Unverified Teacher",
        role=UserRole.teacher,
        is_active=True,
        email_verified=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _cookies(user: User) -> dict[str, str]:
    token, _jti, _exp = create_access_token(user)
    return {"access_token": token, "csrf_token": "test-csrf-fixed-value"}


# ── POST /auth/verify-email ─────────────────────────────────────────────────

async def test_verify_email_post_success(client: AsyncClient, db_session: Any) -> None:
    user = await _make_unverified_teacher(db_session)
    token = email_token_service.issue(str(user.id))

    resp = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert resp.status_code == 200
    assert resp.json() == {"email_verified": True}

    await db_session.refresh(user)
    assert user.email_verified is True


async def test_verify_email_post_token_is_one_time(
    client: AsyncClient, db_session: Any
) -> None:
    user = await _make_unverified_teacher(db_session)
    token = email_token_service.issue(str(user.id))

    first = await client.post("/api/v1/auth/verify-email", json={"token": token})
    second = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"] == "used"


async def test_verify_email_post_invalid_token(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/verify-email", json={"token": "garbage"})
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid"


# ── require_verified_email AI gate ──────────────────────────────────────────

async def test_unverified_teacher_blocked_from_ai_endpoint(
    client: AsyncClient, db_session: Any
) -> None:
    user = await _make_unverified_teacher(db_session)
    resp = await client.post(_QUIZ_GENERATE, json={}, cookies=_cookies(user))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "email_not_verified"


async def test_ai_gate_opens_after_verification(
    client: AsyncClient, db_session: Any
) -> None:
    user = await _make_unverified_teacher(db_session)
    cookies = _cookies(user)

    blocked = await client.post(_QUIZ_GENERATE, json={}, cookies=cookies)
    assert blocked.status_code == 403

    token = email_token_service.issue(str(user.id))
    verified = await client.post("/api/v1/auth/verify-email", json={"token": token})
    assert verified.status_code == 200

    # Same session, now verified: the gate lets the request through (the lesson
    # id is bogus, so it 404s downstream — the point is it is no longer 403).
    after = await client.post(_QUIZ_GENERATE, json={}, cookies=cookies)
    assert after.status_code != 403
