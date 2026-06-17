"""Password reset (forgot / reset) and authenticated change-password flows."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import fakeredis.aioredis
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.password_reset_token import PasswordResetToken
from app.models.user import User, UserRole
from app.services import password_reset_service
from app.services.auth_service import AuthService, hash_password, verify_password

pytestmark = pytest.mark.integration

_OLD_PASSWORD = "old-password-123"
_NEW_PASSWORD = "new-password-456"


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


async def _make_user(db: Any, *, password: str = _OLD_PASSWORD) -> User:
    user = User(
        email=_email(),
        hashed_password=hash_password(password),
        full_name="Reset Target",
        role=UserRole.teacher,
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _issue_raw_token(db: Any, user: User) -> str:
    raw = await password_reset_service.issue(db, str(user.id))
    await db.commit()
    return raw


# ── POST /auth/forgot-password (anonymous, non-enumerating) ─────────────────

async def test_forgot_password_existing_account_sends_email(
    client: AsyncClient, db_session: Any, mock_send_email: Any
) -> None:
    user = await _make_user(db_session)

    resp = await client.post("/api/v1/auth/forgot-password", json={"email": user.email})
    assert resp.status_code == 204

    mock_send_email.assert_called_once()
    kwargs = mock_send_email.call_args.kwargs
    assert kwargs["to"] == user.email
    assert kwargs["template_name"] == "reset_password.html"
    assert "token=" in kwargs["context"]["reset_url"]

    # A token row was actually persisted for the account.
    rows = (
        await db_session.scalars(
            select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
        )
    ).all()
    assert len(rows) == 1


async def test_forgot_password_unknown_email_is_silent(
    client: AsyncClient, mock_send_email: Any
) -> None:
    resp = await client.post(
        "/api/v1/auth/forgot-password", json={"email": "nobody@example.com"}
    )
    # Same 204 as the existing-account case — no enumeration signal — and no mail.
    assert resp.status_code == 204
    mock_send_email.assert_not_called()


# ── POST /auth/reset-password (anonymous, one-time token) ───────────────────

async def test_reset_password_success(client: AsyncClient, db_session: Any) -> None:
    user = await _make_user(db_session)
    raw = await _issue_raw_token(db_session, user)

    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw, "new_password": _NEW_PASSWORD},
    )
    assert resp.status_code == 200

    await db_session.refresh(user)
    assert verify_password(_NEW_PASSWORD, user.hashed_password) is True
    assert verify_password(_OLD_PASSWORD, user.hashed_password) is False

    # Token is burned.
    row = await db_session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    assert row.used_at is not None


async def test_reset_password_reused_token_rejected(
    client: AsyncClient, db_session: Any
) -> None:
    user = await _make_user(db_session)
    raw = await _issue_raw_token(db_session, user)

    first = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw, "new_password": _NEW_PASSWORD},
    )
    second = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw, "new_password": "another-password-789"},
    )
    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"] == "invalid_or_expired"


async def test_reset_password_expired_token_rejected(
    client: AsyncClient, db_session: Any
) -> None:
    user = await _make_user(db_session)
    raw = await _issue_raw_token(db_session, user)

    row = await db_session.scalar(
        select(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    row.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw, "new_password": _NEW_PASSWORD},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_or_expired"
    # Password untouched.
    await db_session.refresh(user)
    assert verify_password(_OLD_PASSWORD, user.hashed_password) is True


async def test_reset_password_invalid_token_rejected(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": "not-a-real-token", "new_password": _NEW_PASSWORD},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "invalid_or_expired"


async def test_reset_password_revokes_all_sessions(db_session: Any) -> None:
    """Service-level: a successful reset wipes every refresh family. Driven
    directly (not via the route) so we control the fake Redis the families
    live in."""
    user = await _make_user(db_session)
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    await redis.set(f"refresh:{user.id}:fam-a", "{}")
    await redis.set(f"refresh:{user.id}:fam-b", "{}")

    service = AuthService(db_session, redis)
    await service.reset_password(user, _NEW_PASSWORD)

    assert await redis.keys(f"refresh:{user.id}:*") == []
    await redis.aclose()


# ── POST /auth/change-password (authenticated + CSRF) ───────────────────────

async def test_change_password_success(
    client: AsyncClient, teacher_user: Any, teacher_token: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "teacher-pass-123", "new_password": _NEW_PASSWORD},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    # Rotated session: fresh auth cookies are set on the response.
    assert "access_token" in resp.headers.get("set-cookie", "")


async def test_change_password_persists_new_hash(
    client: AsyncClient, db_session: Any, teacher_user: Any, teacher_token: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "teacher-pass-123", "new_password": _NEW_PASSWORD},
        cookies=teacher_token,
    )
    assert resp.status_code == 200

    await db_session.refresh(teacher_user)
    assert verify_password(_NEW_PASSWORD, teacher_user.hashed_password) is True


async def test_change_password_wrong_old_rejected(
    client: AsyncClient, db_session: Any, teacher_user: Any, teacher_token: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"old_password": "definitely-wrong", "new_password": _NEW_PASSWORD},
        cookies=teacher_token,
    )
    assert resp.status_code == 400

    await db_session.refresh(teacher_user)
    # Unchanged.
    assert verify_password("teacher-pass-123", teacher_user.hashed_password) is True
