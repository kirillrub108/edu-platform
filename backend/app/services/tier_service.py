"""Tier-based Celery scheduling priority.

A "tier" (free|paid|enterprise) is DERIVED from the billing CreditPlan via
PLAN_TIER_MAP — there is no separate tier column. Its only job here is to pick
the apply_async priority so paid jobs are scheduled ahead of free ones. Spend
itself is governed by credits (see billing_service), not by quotas.

Async only (FastAPI / AsyncSession); never imported into app/tasks/* (sync Celery).
"""
import enum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import PLAN_TIER_MAP, TIER_PRIORITY
from app.models.credit import CreditPlan
from app.services import billing_service


class Tier(str, enum.Enum):
    free = "free"
    paid = "paid"
    enterprise = "enterprise"


def tier_for_plan(plan: "CreditPlan | str") -> Tier:
    key = plan.value if isinstance(plan, CreditPlan) else plan
    return Tier(PLAN_TIER_MAP.get(key, Tier.free.value))


def priority_for_tier(tier: Tier) -> int:
    return TIER_PRIORITY[tier.value]


async def priority_for_user(db: AsyncSession, user_id: UUID) -> int:
    """Celery apply_async priority for the user's plan-derived tier."""
    account = await billing_service.get_or_create_account(db, user_id)
    return priority_for_tier(tier_for_plan(account.plan))
