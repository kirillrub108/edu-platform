"""Credit balance endpoint + admin grant response freshness."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.credit import CreditOperation
from app.models.user import User
from app.services import billing_service

pytestmark = pytest.mark.integration


async def test_balance_reflects_reservation(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    # Free plan starts with 50 one-time credits.
    base = await client.get("/api/v1/billing/balance", cookies=teacher_token)
    assert base.status_code == 200
    assert base.json() == {"balance": 50, "reserved": 0, "available": 50, "plan": "free"}

    await billing_service.reserve_credits(
        db_session, teacher_user.id, 10, "ref-test", CreditOperation.RESERVE
    )

    after = await client.get("/api/v1/billing/balance", cookies=teacher_token)
    body = after.json()
    assert body["balance"] == 50
    assert body["reserved"] == 10
    assert body["available"] == 40


async def test_admin_grant_returns_fresh_balance(
    client: AsyncClient,
    teacher_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ADMIN_API_TOKEN", "secret-admin-token")

    resp = await client.post(
        "/api/v1/billing/admin/credits/grant",
        json={"user_id": str(teacher_user.id), "amount": 25, "description": "Top-up"},
        headers={"X-Admin-Token": "secret-admin-token"},
    )
    assert resp.status_code == 200
    body = resp.json()
    # 50 starting credits + 25 granted.
    assert body["balance"] == 75
    assert body["reserved"] == 0
    assert body["available"] == 75
    assert body["delta"] == 25
