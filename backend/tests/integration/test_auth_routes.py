"""End-to-end auth routes (register/login/refresh/me)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.constants import CONSENT_POLICY_VERSION
from app.models.user import User

pytestmark = pytest.mark.integration


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


# The two mandatory registration consents, spread into every register payload.
_CONSENTS = {"accepted_privacy": True, "accepted_terms": True}


async def test_register_returns_user_payload(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": _email(),
            "password": "password123",
            "full_name": "Alice",
            "role": "teacher",
            **_CONSENTS,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "teacher"
    assert body["is_active"] is True
    assert "id" in body


async def test_register_without_consents_is_rejected_and_creates_no_user(
    client: AsyncClient, db_session: Any
) -> None:
    email = _email()
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "role": "teacher"},
    )
    assert resp.status_code == 422
    assert await db_session.scalar(select(User).where(User.email == email)) is None


async def test_register_missing_one_required_consent_is_rejected(client: AsyncClient) -> None:
    # Privacy accepted but terms omitted — still a 422.
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": _email(),
            "password": "password123",
            "role": "teacher",
            "accepted_privacy": True,
        },
    )
    assert resp.status_code == 422


async def test_register_records_consents_with_marketing(
    client: AsyncClient, db_session: Any
) -> None:
    email = _email()
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password123",
            "role": "teacher",
            "accepted_privacy": True,
            "accepted_terms": True,
            "accepted_marketing": True,
        },
        headers={"X-Forwarded-For": "203.0.113.7"},
    )
    assert resp.status_code == 201

    user = await db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    assert user.pdn_consent_at is not None
    assert user.terms_accepted_at is not None
    assert user.consent_policy_version == CONSENT_POLICY_VERSION
    assert user.consent_ip == "203.0.113.7"
    assert user.marketing_consent is True
    assert user.marketing_consent_at is not None


async def test_register_without_marketing_leaves_marketing_unset(
    client: AsyncClient, db_session: Any
) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "password123",
            "role": "teacher",
            "accepted_privacy": True,
            "accepted_terms": True,
        },
    )
    user = await db_session.scalar(select(User).where(User.email == email))
    assert user.marketing_consent is False
    assert user.marketing_consent_at is None


async def test_register_duplicate_email_returns_409(client: AsyncClient) -> None:
    email = _email()
    payload = {"email": email, "password": "password123", "role": "teacher", **_CONSENTS}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    dup = await client.post("/api/v1/auth/register", json=payload)
    assert dup.status_code == 409
    assert "already registered" in dup.json()["detail"].lower()


async def test_login_sets_auth_cookies(client: AsyncClient) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "role": "teacher", **_CONSENTS},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 200
    # Tokens must arrive in cookies, not in the response body
    assert "access_token" not in resp.json()
    assert "access_token" in resp.cookies
    assert "refresh_token" in resp.cookies
    assert "csrf_token" in resp.cookies


async def test_login_with_wrong_password_returns_401(client: AsyncClient) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "role": "teacher", **_CONSENTS},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WRONG"},
    )
    assert resp.status_code == 401
    assert "credentials" in resp.json()["detail"].lower()


async def test_refresh_rotates_cookies(client: AsyncClient) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "role": "teacher", **_CONSENTS},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    old_access = client.cookies.get("access_token")
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 200
    assert "access_token" in resp.cookies
    assert resp.cookies["access_token"] != old_access


async def test_refresh_without_cookie_returns_401(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/refresh")
    assert resp.status_code == 401


async def test_refresh_rejects_access_token_as_refresh_cookie(
    client: AsyncClient,
) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "role": "teacher", **_CONSENTS},
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    access = login_resp.cookies["access_token"]

    resp = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": access},
    )
    assert resp.status_code == 401


async def test_me_returns_current_user(
    client: AsyncClient, teacher_user: Any, teacher_token: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/auth/me", cookies=teacher_token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(teacher_user.id)
    assert body["email"] == teacher_user.email


async def test_logout_clears_auth_cookies(client: AsyncClient) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "role": "teacher", **_CONSENTS},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    # Session is live before logout.
    assert (await client.get("/api/v1/auth/me")).status_code == 200

    resp = await client.post("/api/v1/auth/logout")
    assert resp.status_code == 204

    # The logout response MUST explicitly expire all three cookies. Otherwise the
    # browser keeps the httpOnly access/refresh tokens and the session silently
    # survives (a 401 on /auth/me would just be refreshed back into a session).
    set_cookie = "\n".join(resp.headers.get_list("set-cookie")).lower()
    for name in ("access_token", "refresh_token", "csrf_token"):
        assert name in set_cookie, f"logout did not clear {name}"
    assert "max-age=0" in set_cookie

    # Cookie jar cleared client-side → subsequent probe is anonymous.
    assert (await client.get("/api/v1/auth/me")).status_code in (401, 403)


async def test_logout_revokes_refresh_family(client: AsyncClient) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "role": "teacher", **_CONSENTS},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    # Capture the refresh token as an attacker who exfiltrated it would.
    stolen_refresh = client.cookies.get("refresh_token")
    assert stolen_refresh

    assert (await client.post("/api/v1/auth/logout")).status_code == 204

    # Replaying the stolen refresh token must fail: logout revoked the family
    # server-side, so it is dead even though the cookie clear alone wouldn't
    # stop an exfiltrated copy.
    resp = await client.post(
        "/api/v1/auth/refresh",
        cookies={"refresh_token": stolen_refresh},
    )
    assert resp.status_code == 401


async def test_me_without_token_rejects_unauthorized(client: AsyncClient) -> None:
    # No token → endpoint rejects with an auth-error status. We accept both
    # 401 (Unauthorized) and 403 (Forbidden) so the test does not pin the
    # specific HTTPBearer/middleware behavior, which differs across FastAPI
    # versions.
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code in (401, 403)
