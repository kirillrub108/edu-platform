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
    # Free plan starts with zero credits — the lifetime trial replaces the
    # former welcome grant.
    base = await client.get("/api/v1/billing/balance", cookies=teacher_token)
    assert base.status_code == 200
    body = base.json()
    assert body["balance"] == 0
    assert body["reserved"] == 0
    assert body["available"] == 0
    assert body["plan"] == "free"
    # Fresh account: full lifetime trial reported alongside the balance.
    assert body["trial"] == {
        "lectures_used": 0,
        "lectures_limit": 2,
        "quizzes_used": 0,
        "quizzes_limit": 2,
    }

    await billing_service.grant_credits(db_session, teacher_user.id, 50, "seed")
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
    assert body["balance"] == 25
    assert body["reserved"] == 0
    assert body["available"] == 25
    assert body["delta"] == 25
