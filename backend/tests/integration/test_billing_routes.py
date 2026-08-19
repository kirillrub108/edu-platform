"""Credit balance endpoint + admin grant response freshness."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import AI_GRADING_FREE_ANSWERS_PER_MONTH
from app.models.credit import CreditOperation
from app.models.user import User
from app.services import billing_service, quota_service

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


# ── Monthly AI-grading allowance (exposed alongside the trial state) ─────────


async def test_balance_reports_the_monthly_ai_grading_quota(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    resp = await client.get("/api/v1/billing/balance", cookies=teacher_token)
    assert resp.status_code == 200
    quota = resp.json()["ai_grading"]

    assert quota["limit"] == AI_GRADING_FREE_ANSWERS_PER_MONTH
    assert quota["used"] == 0
    assert quota["remaining"] == AI_GRADING_FREE_ANSWERS_PER_MONTH
    # The reset date is the start of next month, so it is always in the future.
    assert datetime.fromisoformat(quota["resets_at"]) > datetime.now(timezone.utc)


async def test_quota_usage_is_reflected_and_never_goes_negative(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    """Consuming slots lowers `remaining`; overshooting the limit clamps it at
    zero rather than rendering a negative number in the UI."""
    period = quota_service.utc_month_key()
    for _ in range(3):
        await quota_service.try_consume_slot(
            db_session, teacher_user.id, quota_service.AI_GRADING, 100, period
        )

    quota = (await client.get("/api/v1/billing/balance", cookies=teacher_token)).json()[
        "ai_grading"
    ]
    assert quota["used"] == 3
    assert quota["remaining"] == AI_GRADING_FREE_ANSWERS_PER_MONTH - 3

    # Force the counter past the limit the way a lowered constant would.
    await db_session.execute(
        text(
            "UPDATE usage_counters SET count = :n WHERE user_id = :uid "
            "AND resource = :res AND period_key = :pk"
        ),
        {
            "n": AI_GRADING_FREE_ANSWERS_PER_MONTH + 50,
            "uid": teacher_user.id,
            "res": quota_service.AI_GRADING,
            "pk": period,
        },
    )
    await db_session.commit()

    quota = (await client.get("/api/v1/billing/balance", cookies=teacher_token)).json()[
        "ai_grading"
    ]
    assert quota["remaining"] == 0
