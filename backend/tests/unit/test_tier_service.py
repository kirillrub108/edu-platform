"""tier_service: map a billing plan to a tier and to the Celery priority.

The mapping cases are pure `unit` tests; priority_for_user needs the
PostgreSQL testcontainer (it reads the credit account), so it is `integration`.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TIER_PRIORITY
from app.models.credit import CreditPlan
from app.models.user import User
from app.services import billing_service, tier_service
from app.services.tier_service import Tier


@pytest.mark.unit
@pytest.mark.parametrize(
    ("plan", "tier"),
    [
        (CreditPlan.free, Tier.free),
        (CreditPlan.starter, Tier.paid),
        (CreditPlan.pro, Tier.paid),
        (CreditPlan.school, Tier.paid),
    ],
)
def test_tier_for_plan(plan: CreditPlan, tier: Tier) -> None:
    assert tier_service.tier_for_plan(plan) is tier
    assert tier_service.tier_for_plan(plan.value) is tier


@pytest.mark.unit
def test_tier_for_plan_unknown_defaults_to_free() -> None:
    assert tier_service.tier_for_plan("mystery-plan") is Tier.free


@pytest.mark.unit
def test_priority_ordering_enterprise_is_highest() -> None:
    # Redis broker: a LOWER number is HIGHER priority, so enterprise (highest)
    # must map to the smallest value and free (lowest) to the largest.
    enterprise = tier_service.priority_for_tier(Tier.enterprise)
    paid = tier_service.priority_for_tier(Tier.paid)
    free = tier_service.priority_for_tier(Tier.free)
    assert enterprise < paid < free
    assert free == TIER_PRIORITY["free"]


@pytest.mark.integration
async def test_priority_for_user_free_default(
    db_session: AsyncSession, teacher_user: User
) -> None:
    # A fresh account is on the free plan → lowest priority.
    pr = await tier_service.priority_for_user(db_session, teacher_user.id)
    assert pr == TIER_PRIORITY["free"]


@pytest.mark.integration
async def test_priority_for_user_paid_plan(
    db_session: AsyncSession, teacher_user: User
) -> None:
    account = await billing_service.get_or_create_account(db_session, teacher_user.id)
    account.plan = CreditPlan.pro
    await db_session.commit()

    pr = await tier_service.priority_for_user(db_session, teacher_user.id)
    assert pr == TIER_PRIORITY["paid"]
    assert pr < TIER_PRIORITY["free"]
