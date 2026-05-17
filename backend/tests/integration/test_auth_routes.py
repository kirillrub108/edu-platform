"""End-to-end auth routes (register/login/refresh/me)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


def _email() -> str:
    return f"user-{uuid.uuid4().hex[:10]}@example.com"


async def test_register_returns_user_payload(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": _email(),
            "password": "password123",
            "full_name": "Alice",
            "role": "teacher",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "teacher"
    assert body["is_active"] is True
    assert "id" in body


async def test_register_duplicate_email_returns_409(client: AsyncClient) -> None:
    email = _email()
    payload = {"email": email, "password": "password123", "role": "teacher"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    dup = await client.post("/api/v1/auth/register", json=payload)
    assert dup.status_code == 409
    assert "already registered" in dup.json()["detail"].lower()


async def test_login_returns_token_pair(client: AsyncClient) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "role": "teacher"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body
    assert body["token_type"] == "bearer"


async def test_login_with_wrong_password_returns_401(client: AsyncClient) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "role": "teacher"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WRONG"},
    )
    assert resp.status_code == 401
    assert "credentials" in resp.json()["detail"].lower()


async def test_refresh_returns_new_pair(client: AsyncClient) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "role": "teacher"},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    refresh_token = login.json()["refresh_token"]

    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] != login.json()["access_token"]
    assert body["refresh_token"] != refresh_token


async def test_refresh_rejects_access_token_in_refresh_field(
    client: AsyncClient,
) -> None:
    email = _email()
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123", "role": "teacher"},
    )
    login = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    access = login.json()["access_token"]

    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": access})
    assert resp.status_code == 401


async def test_me_returns_current_user(
    client: AsyncClient, teacher_user: Any, teacher_token: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/auth/me", headers=teacher_token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == str(teacher_user.id)
    assert body["email"] == teacher_user.email


async def test_me_without_token_rejects_unauthorized(client: AsyncClient) -> None:
    # No token → endpoint rejects with an auth-error status. We accept both
    # 401 (Unauthorized) and 403 (Forbidden) so the test does not pin the
    # specific HTTPBearer/middleware behavior, which differs across FastAPI
    # versions.
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code in (401, 403)
