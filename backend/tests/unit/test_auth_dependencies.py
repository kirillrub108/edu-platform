"""Unit tests for cookie-based auth dependencies.

Covers: no cookie → 401, valid cookie → user, bad CSRF on POST → 403.
Uses a minimal FastAPI app with mocked DB and fakeredis — no postgres needed.
"""
from __future__ import annotations

import secrets
import uuid
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.models.user import User, UserRole
from app.services.auth_service import create_access_token


def _mock_user() -> MagicMock:
    user = MagicMock(spec=User)
    user.id = uuid.uuid4()
    user.email = "test@example.com"
    user.role = UserRole.teacher
    user.is_active = True
    return user


@pytest.fixture
def auth_app():
    """Minimal FastAPI app with cookie auth and mocked DB/Redis."""
    from app.database import get_db
    from app.dependencies import get_current_user
    from app.redis_client import get_redis

    app = FastAPI()
    user = _mock_user()
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=True)

    @app.get("/protected")
    async def _get(current_user=Depends(get_current_user)):
        return {"user_id": str(current_user.id)}

    @app.post("/protected")
    async def _post(current_user=Depends(get_current_user)):
        return {"user_id": str(current_user.id)}

    async def _mock_db():
        session = AsyncMock()
        session.get = AsyncMock(return_value=user)
        yield session

    async def _mock_redis():
        return fake_redis

    app.dependency_overrides[get_db] = _mock_db
    app.dependency_overrides[get_redis] = _mock_redis

    return app, user


@pytest.mark.asyncio
async def test_no_cookie_returns_401(auth_app) -> None:
    app, _ = auth_app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/protected")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_valid_cookie_returns_user(auth_app) -> None:
    app, user = auth_app
    token, _, _ = create_access_token(user)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/protected", cookies={"access_token": token})
    assert resp.status_code == 200
    assert resp.json()["user_id"] == str(user.id)


@pytest.mark.asyncio
async def test_post_with_missing_csrf_returns_403(auth_app) -> None:
    app, user = auth_app
    token, _, _ = create_access_token(user)
    csrf = secrets.token_hex(32)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Has csrf_token cookie but no X-CSRF-Token header
        resp = await ac.post(
            "/protected",
            cookies={"access_token": token, "csrf_token": csrf},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_with_wrong_csrf_returns_403(auth_app) -> None:
    app, user = auth_app
    token, _, _ = create_access_token(user)
    csrf = secrets.token_hex(32)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/protected",
            cookies={"access_token": token, "csrf_token": csrf},
            headers={"X-CSRF-Token": "wrong-value"},
        )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_post_with_valid_csrf_returns_user(auth_app) -> None:
    app, user = auth_app
    token, _, _ = create_access_token(user)
    csrf = secrets.token_hex(32)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/protected",
            cookies={"access_token": token, "csrf_token": csrf},
            headers={"X-CSRF-Token": csrf},
        )
    assert resp.status_code == 200
    assert resp.json()["user_id"] == str(user.id)
