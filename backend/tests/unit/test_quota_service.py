"""quota_service: tier→priority mapping, atomic monthly reservation, concurrency
count, and best-effort release.

The DB-bound cases need the PostgreSQL testcontainer, so they carry the
`integration` marker even though they live under tests/unit/ (they exercise the
service, not a route). The mapping cases are true `unit` tests.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TIER_PRIORITY, TIER_QUOTAS
from app.models.credit import CreditPlan
from app.models.lesson import LessonStatus
from app.models.usage_counter import UsageCounter, UsageResource
from app.models.user import User
from app.services import quota_service
from app.services.quota_service import ConcurrencyLimitError, QuotaExceededError, Tier
from tests.factories import make_course, make_lesson, make_module

# ── Pure mapping (no DB) ─────────────────────────────────────────────────────


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
    assert quota_service.tier_for_plan(plan) is tier
    assert quota_service.tier_for_plan(plan.value) is tier


@pytest.mark.unit
def test_tier_for_plan_unknown_defaults_to_free() -> None:
    assert quota_service.tier_for_plan("mystery-plan") is Tier.free


@pytest.mark.unit
def test_priority_ordering_enterprise_is_highest() -> None:
    # Redis broker: a LOWER number is HIGHER priority, so enterprise (highest)
    # must map to the smallest value and free (lowest) to the largest.
    enterprise = quota_service.priority_for_tier(Tier.enterprise)
    paid = quota_service.priority_for_tier(Tier.paid)
    free = quota_service.priority_for_tier(Tier.free)
    assert enterprise < paid < free
    assert free == TIER_PRIORITY["free"]


# ── DB-bound reservation / concurrency / release ─────────────────────────────


async def _period_count(
    db: AsyncSession, user_id, resource: UsageResource
) -> int | None:
    return await db.scalar(
        select(UsageCounter.count).where(
            UsageCounter.user_id == user_id,
            UsageCounter.period_key == quota_service._current_period_key(),
            UsageCounter.resource == resource,
        )
    )


@pytest.mark.integration
async def test_reserve_within_limit_increments_and_returns_priority(
    db_session: AsyncSession, teacher_user: User
) -> None:
    pr = await quota_service.reserve(db_session, teacher_user.id, UsageResource.video)
    assert pr == TIER_PRIORITY["free"]  # default plan → free tier
    assert await _period_count(db_session, teacher_user.id, UsageResource.video) == 1

    pr2 = await quota_service.reserve(db_session, teacher_user.id, UsageResource.video)
    assert pr2 == TIER_PRIORITY["free"]
    assert await _period_count(db_session, teacher_user.id, UsageResource.video) == 2


@pytest.mark.integration
async def test_reserve_over_limit_raises_and_does_not_overcount(
    db_session: AsyncSession, teacher_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Shrink the limit so the boundary is cheap. The atomicity itself lives in the
    # single-statement UPSERT (a real parallel race can't run on the shared test
    # connection), so we assert the WHERE guard deterministically instead.
    monkeypatch.setitem(TIER_QUOTAS["free"], "monthly_video", 1)

    pr = await quota_service.reserve(db_session, teacher_user.id, UsageResource.video)
    assert pr == TIER_PRIORITY["free"]
    assert await _period_count(db_session, teacher_user.id, UsageResource.video) == 1

    with pytest.raises(QuotaExceededError) as ei:
        await quota_service.reserve(db_session, teacher_user.id, UsageResource.video)
    assert ei.value.status_code == 402
    assert ei.value.detail["code"] == "quota_exceeded"
    assert ei.value.detail["resource"] == "video"
    assert ei.value.detail["limit"] == 1
    assert ei.value.detail["used"] == 1
    # The rejected attempt must not push the counter past the limit.
    assert await _period_count(db_session, teacher_user.id, UsageResource.video) == 1


@pytest.mark.integration
async def test_release_decrements_and_clamps_at_zero(
    db_session: AsyncSession, teacher_user: User
) -> None:
    await quota_service.reserve(db_session, teacher_user.id, UsageResource.vision)
    assert await _period_count(db_session, teacher_user.id, UsageResource.vision) == 1

    await quota_service.release(db_session, teacher_user.id, UsageResource.vision)
    assert await _period_count(db_session, teacher_user.id, UsageResource.vision) == 0

    # A second release must not drive the count negative.
    await quota_service.release(db_session, teacher_user.id, UsageResource.vision)
    assert await _period_count(db_session, teacher_user.id, UsageResource.vision) == 0


@pytest.mark.integration
async def test_active_job_count_only_counts_in_flight_lessons(
    db_session: AsyncSession, teacher_user: User
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    await make_lesson(db_session, module, status=LessonStatus.processing)
    await make_lesson(db_session, module, status=LessonStatus.analyzing)
    await make_lesson(db_session, module, status=LessonStatus.published)
    await make_lesson(db_session, module, status=LessonStatus.draft)

    assert await quota_service._active_job_count(db_session, teacher_user.id) == 2


@pytest.mark.integration
async def test_reserve_concurrency_limit_raises_without_incrementing(
    db_session: AsyncSession, teacher_user: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(TIER_QUOTAS["free"], "max_concurrent_jobs", 1)
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    await make_lesson(db_session, module, status=LessonStatus.processing)  # 1 active

    with pytest.raises(ConcurrencyLimitError) as ei:
        await quota_service.reserve(db_session, teacher_user.id, UsageResource.video)
    assert ei.value.status_code == 429
    assert ei.value.detail["code"] == "concurrency_limit"
    assert ei.value.detail["limit"] == 1
    assert ei.value.detail["active"] == 1
    assert ei.value.headers["Retry-After"]
    # A concurrency rejection must not touch the monthly counter.
    assert await _period_count(db_session, teacher_user.id, UsageResource.video) in (None, 0)
