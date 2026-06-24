"""Email-verification routes + the require_verified_teacher content gate.

send_email is stubbed by the autouse `mock_send_email` fixture, so no provider
is ever contacted.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

from app.config import settings
from app.models.user import User, UserRole
from app.services.auth_service import (
    create_access_token,
    generate_email_verification_token,
    hash_password,
)

pytestmark = pytest.mark.integration


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


# ── Registration ──────────────────────────────────────────────────────────────

async def test_register_creates_unverified_user_and_enqueues_email(
    client: AsyncClient, mock_send_email: Any
) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": _email(),
            "password": "password123",
            "role": "teacher",
            "accepted_privacy": True,
            "accepted_terms": True,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["email_verified"] is False

    mock_send_email.assert_called_once()
    kwargs = mock_send_email.call_args.kwargs
    assert kwargs["template_name"] == "verify_email.html"
    assert "token=" in kwargs["context"]["verify_url"]


# ── verify-email ──────────────────────────────────────────────────────────────

async def test_verify_email_marks_verified_and_redirects(
    client: AsyncClient, db_session: Any
) -> None:
    user = await _make_unverified_teacher(db_session)
    token = generate_email_verification_token(str(user.id))

    resp = await client.get(f"/api/v1/auth/verify-email?token={token}")
    assert resp.status_code == 302
    assert resp.headers["location"] == f"{settings.FRONTEND_URL}/login?verified=1"

    await db_session.refresh(user)
    assert user.email_verified is True


async def test_verify_email_is_idempotent(client: AsyncClient, db_session: Any) -> None:
    user = await _make_unverified_teacher(db_session)
    token = generate_email_verification_token(str(user.id))

    first = await client.get(f"/api/v1/auth/verify-email?token={token}")
    second = await client.get(f"/api/v1/auth/verify-email?token={token}")
    assert first.status_code == second.status_code == 302
    assert second.headers["location"] == f"{settings.FRONTEND_URL}/login?verified=1"


async def test_verify_email_invalid_token_redirects_not_500(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/verify-email?token=not-a-real-token")
    assert resp.status_code == 302
    assert "verified=0" in resp.headers["location"]
    assert "reason=invalid" in resp.headers["location"]


# ── Structural CRUD is open to unverified teachers ──────────────────────────────
# Creating course/module/lesson structure no longer requires a verified email;
# only AI operations stay gated (see test_verify_email_post.py).

async def test_unverified_teacher_can_create_structure(
    client: AsyncClient, db_session: Any
) -> None:
    user = await _make_unverified_teacher(db_session)
    cookies = _cookies(user)

    course = await client.post(
        "/api/v1/courses/", json={"title": "Open course"}, cookies=cookies
    )
    assert course.status_code == 201
    course_id = course.json()["id"]

    module = await client.post(
        f"/api/v1/courses/{course_id}/modules",
        json={"title": "Module 1", "order": 0},
        cookies=cookies,
    )
    assert module.status_code == 201
    module_id = module.json()["id"]

    lesson = await client.post(
        "/api/v1/lessons/",
        json={"title": "Lesson 1", "module_id": module_id},
        cookies=cookies,
    )
    assert lesson.status_code == 201


async def test_unverified_teacher_can_still_read(client: AsyncClient, db_session: Any) -> None:
    user = await _make_unverified_teacher(db_session)
    # GET endpoints are not gated — listing must work even while unverified.
    resp = await client.get("/api/v1/courses/", cookies=_cookies(user))
    assert resp.status_code == 200


async def test_verified_teacher_can_create_course(
    client: AsyncClient, teacher_user: Any, teacher_token: dict[str, str]
) -> None:
    # teacher_user fixture is email_verified=True.
    resp = await client.post(
        "/api/v1/courses/",
        json={"title": "Allowed course"},
        cookies=teacher_token,
    )
    assert resp.status_code == 201


# ── resend-verification ───────────────────────────────────────────────────────

async def test_resend_for_unverified_enqueues(
    client: AsyncClient, db_session: Any, mock_send_email: Any
) -> None:
    user = await _make_unverified_teacher(db_session)
    resp = await client.post("/api/v1/auth/resend-verification", cookies=_cookies(user))
    assert resp.status_code == 204
    mock_send_email.assert_called_once()


async def test_resend_for_verified_returns_400_no_email(
    client: AsyncClient, teacher_user: Any, teacher_token: dict[str, str], mock_send_email: Any
) -> None:
    resp = await client.post("/api/v1/auth/resend-verification", cookies=teacher_token)
    assert resp.status_code == 400
    mock_send_email.assert_not_called()


async def test_resend_is_rate_limited(client: AsyncClient, db_session: Any) -> None:
    from app.limiter import limiter

    user = await _make_unverified_teacher(db_session)
    cookies = _cookies(user)

    limiter.enabled = True
    try:
        statuses = [
            (await client.post("/api/v1/auth/resend-verification", cookies=cookies)).status_code
            for _ in range(5)
        ]
    finally:
        limiter.enabled = False

    # Limit is 3/minute → at least one later call must be throttled.
    assert 429 in statuses
    assert statuses[0] == 204
