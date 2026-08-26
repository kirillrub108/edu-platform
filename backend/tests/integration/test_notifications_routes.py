"""Notification settings API + public unsubscribe endpoint."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.services.notification_service import (
    NotificationCategory,
    generate_unsubscribe_token,
)

pytestmark = pytest.mark.integration


async def test_settings_default_to_all_on(
    client: AsyncClient, teacher_token: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/notifications/settings", cookies=teacher_token)
    assert resp.status_code == 200
    assert resp.json() == {
        "notify_content": True,
        "notify_feedback": True,
        "notify_submissions": True,
    }


async def test_settings_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/notifications/settings")).status_code == 401


async def test_patch_updates_only_the_named_category(
    client: AsyncClient, teacher_token: dict[str, str]
) -> None:
    resp = await client.patch(
        "/api/v1/notifications/settings",
        json={"notify_feedback": False},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["notify_feedback"] is False
    assert body["notify_content"] is True
    assert body["notify_submissions"] is True


async def test_unsubscribe_link_switches_the_category_off(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    token = generate_unsubscribe_token(str(teacher_user.id), NotificationCategory.content)
    resp = await client.get(f"/api/v1/notifications/unsubscribe?token={token}")

    assert resp.status_code == 302
    assert "status=ok" in resp.headers["location"]
    await db_session.refresh(teacher_user)
    assert teacher_user.notify_content is False
    assert teacher_user.notify_feedback is True


async def test_unsubscribe_is_idempotent(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    token = generate_unsubscribe_token(str(teacher_user.id), NotificationCategory.feedback)
    first = await client.get(f"/api/v1/notifications/unsubscribe?token={token}")
    second = await client.get(f"/api/v1/notifications/unsubscribe?token={token}")

    assert "status=ok" in first.headers["location"]
    assert "status=ok" in second.headers["location"]
    await db_session.refresh(teacher_user)
    assert teacher_user.notify_feedback is False


async def test_forged_token_redirects_without_changing_anything(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    resp = await client.get("/api/v1/notifications/unsubscribe?token=obviously-not-signed")

    assert resp.status_code == 302
    assert "status=invalid" in resp.headers["location"]
    await db_session.refresh(teacher_user)
    assert teacher_user.notify_content is True


async def test_token_for_a_vanished_user_redirects_not_found(client: AsyncClient) -> None:
    token = generate_unsubscribe_token(str(uuid.uuid4()), NotificationCategory.content)
    resp = await client.get(f"/api/v1/notifications/unsubscribe?token={token}")
    assert "status=not_found" in resp.headers["location"]


async def test_one_click_post_unsubscribes_without_a_session(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    """RFC 8058: the mail client POSTs with no cookies and no CSRF header."""
    token = generate_unsubscribe_token(str(teacher_user.id), NotificationCategory.submissions)
    resp = await client.post(f"/api/v1/notifications/unsubscribe?token={token}")

    assert resp.status_code == 204
    await db_session.refresh(teacher_user)
    assert teacher_user.notify_submissions is False
