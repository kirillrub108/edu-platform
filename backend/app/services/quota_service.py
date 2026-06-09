"""Tier-based quotas: monthly caps on metered AI ops + concurrency limit, plus
the Celery scheduling priority for a user's tier.

The "tier" (free|paid|enterprise) is derived from the billing CreditPlan via
PLAN_TIER_MAP — there is no separate tier column. All limits/priority come from
constants.py (TIER_QUOTAS / TIER_PRIORITY), never hard-coded here.

Async only (FastAPI / AsyncSession). Quotas are reserved in the router BEFORE
enqueue; nothing here is imported into app/tasks/* (sync Celery).

Reservation model:
  reserve(...)  → concurrency gate + atomic monthly UPSERT; returns the tier
                  priority to pass to apply_async. Raises on rejection WITHOUT
                  incrementing the counter.
  release(...)  → best-effort decrement, used to compensate a failed enqueue.
"""
import enum
from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    CONCURRENCY_RETRY_AFTER_SECONDS,
    PLAN_TIER_MAP,
    TIER_PRIORITY,
    TIER_QUOTAS,
)
from app.models.course import Course
from app.models.credit import CreditPlan
from app.models.lesson import Lesson, LessonStatus, Module
from app.models.usage_counter import UsageCounter, UsageResource
from app.services import billing_service

logger = structlog.get_logger()


class Tier(str, enum.Enum):
    free = "free"
    paid = "paid"
    enterprise = "enterprise"


# UsageResource → the TIER_QUOTAS monthly-limit key for that resource.
_RESOURCE_QUOTA_KEY: dict[UsageResource, str] = {
    UsageResource.video: "monthly_video",
    UsageResource.vision: "monthly_vision",
}


class QuotaExceededError(HTTPException):
    """402 — the user's monthly quota for this resource is used up."""

    def __init__(self, resource: UsageResource, limit: int, used: int) -> None:
        super().__init__(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "quota_exceeded",
                "resource": resource.value,
                "limit": limit,
                "used": used,
            },
        )


class ConcurrencyLimitError(HTTPException):
    """429 — the user already has max_concurrent_jobs active jobs."""

    def __init__(self, limit: int, active: int) -> None:
        super().__init__(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "code": "concurrency_limit",
                "limit": limit,
                "active": active,
            },
            headers={"Retry-After": str(CONCURRENCY_RETRY_AFTER_SECONDS)},
        )


def tier_for_plan(plan: "CreditPlan | str") -> Tier:
    key = plan.value if isinstance(plan, CreditPlan) else plan
    return Tier(PLAN_TIER_MAP.get(key, Tier.free.value))


def priority_for_tier(tier: Tier) -> int:
    return TIER_PRIORITY[tier.value]


def _current_period_key() -> str:
    """Month bucket "YYYY-MM" (UTC). A new month is a new row → counters reset
    naturally. Safe here (async router context, not a Celery worker)."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _active_job_count(db: AsyncSession, user_id: UUID) -> int:
    """Lessons the user owns that are currently mid-pipeline. The pipelines
    clear these statuses on finish (success/error), so this is self-correcting —
    no separate counter to drift. Soft-deleted lessons are excluded by the global
    filter in app/database.py."""
    stmt = (
        select(func.count(Lesson.id))
        .select_from(Lesson)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .where(Course.owner_id == user_id)
        .where(Lesson.status.in_((LessonStatus.analyzing, LessonStatus.processing)))
    )
    return (await db.scalar(stmt)) or 0


async def _current_count(
    db: AsyncSession, user_id: UUID, period_key: str, resource: UsageResource
) -> int:
    count = await db.scalar(
        select(UsageCounter.count).where(
            UsageCounter.user_id == user_id,
            UsageCounter.period_key == period_key,
            UsageCounter.resource == resource,
        )
    )
    return count or 0


async def _atomic_reserve(
    db: AsyncSession, user_id: UUID, period_key: str, resource: UsageResource, limit: int
) -> int | None:
    """Atomically claim one unit of monthly quota. Returns the new count, or None
    if the limit is reached.

    The whole check-and-increment is a single statement: INSERT a fresh counter at
    1, or on conflict bump the existing count by 1 ONLY while it is below the
    limit. When the limit is hit the DO UPDATE ... WHERE matches no row and
    RETURNING yields nothing — that "no row" is the quota-exhausted signal. Two
    racing requests for the last slot are serialized by the row lock, so exactly
    one gets a row back.
    """
    if limit <= 0:
        # A zero/negative limit has no first slot — the fresh-INSERT path (which
        # the WHERE clause does not guard) would otherwise wrongly admit one.
        return None
    stmt = (
        pg_insert(UsageCounter)
        .values(user_id=user_id, period_key=period_key, resource=resource, count=1)
        .on_conflict_do_update(
            index_elements=["user_id", "period_key", "resource"],
            set_={"count": UsageCounter.count + 1, "updated_at": func.now()},
            where=UsageCounter.count < limit,
        )
        .returning(UsageCounter.count)
    )
    new_count = (await db.execute(stmt)).scalar_one_or_none()
    await db.commit()
    return new_count


async def reserve(db: AsyncSession, user_id: UUID, resource: UsageResource) -> int:
    """Concurrency gate + atomic monthly reservation. Returns the Celery priority
    for the user's tier (pass straight to apply_async(priority=...)).

    Raises ConcurrencyLimitError (429) or QuotaExceededError (402) on rejection,
    without leaving a counter increment behind.
    """
    account = await billing_service.get_or_create_account(db, user_id)
    tier = tier_for_plan(account.plan)
    quotas = TIER_QUOTAS[tier.value]

    # Concurrency first (read-only): rejecting here must not touch the monthly
    # counter, so it has to run before the reserving UPSERT.
    max_jobs = quotas["max_concurrent_jobs"]
    active = await _active_job_count(db, user_id)
    if active >= max_jobs:
        logger.warning(
            "concurrency_limit_hit",
            user_id=str(user_id),
            tier=tier.value,
            resource=resource.value,
            limit=max_jobs,
            active=active,
        )
        raise ConcurrencyLimitError(limit=max_jobs, active=active)

    limit = quotas[_RESOURCE_QUOTA_KEY[resource]]
    period_key = _current_period_key()
    new_count = await _atomic_reserve(db, user_id, period_key, resource, limit)
    if new_count is None:
        used = await _current_count(db, user_id, period_key, resource)
        logger.warning(
            "quota_exceeded",
            user_id=str(user_id),
            tier=tier.value,
            resource=resource.value,
            limit=limit,
            used=used,
        )
        raise QuotaExceededError(resource, limit, used)

    return priority_for_tier(tier)


async def release(db: AsyncSession, user_id: UUID, resource: UsageResource) -> None:
    """Best-effort decrement of the current month's counter. Compensates a
    reservation whose enqueue then failed. Clamped at 0; a no-op if the row is
    already gone (e.g. month rolled over)."""
    period_key = _current_period_key()
    await db.execute(
        update(UsageCounter)
        .where(
            UsageCounter.user_id == user_id,
            UsageCounter.period_key == period_key,
            UsageCounter.resource == resource,
            UsageCounter.count > 0,
        )
        .values(count=UsageCounter.count - 1, updated_at=func.now())
    )
    await db.commit()


async def get_status(db: AsyncSession, user_id: UUID) -> dict:
    """Current quota snapshot for the frontend (GET /api/v1/quota)."""
    account = await billing_service.get_or_create_account(db, user_id)
    tier = tier_for_plan(account.plan)
    quotas = TIER_QUOTAS[tier.value]
    period_key = _current_period_key()

    used_video = await _current_count(db, user_id, period_key, UsageResource.video)
    used_vision = await _current_count(db, user_id, period_key, UsageResource.vision)
    active = await _active_job_count(db, user_id)

    def _rq(used: int, limit: int) -> dict[str, int]:
        return {"used": used, "limit": limit, "remaining": max(0, limit - used)}

    return {
        "tier": tier.value,
        "period_key": period_key,
        "video": _rq(used_video, quotas["monthly_video"]),
        "vision": _rq(used_vision, quotas["monthly_vision"]),
        "max_concurrent_jobs": quotas["max_concurrent_jobs"],
        "active_jobs": active,
    }
