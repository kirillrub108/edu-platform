"""Tier quotas on the enqueue routes: generate-video and analyze return
200 / 402 / 402-quota / 429, increment the monthly counter, and pass the tier
priority to apply_async (broker mocked)."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TIER_PRIORITY, TIER_QUOTAS
from app.models.credit import CreditPlan
from app.models.lesson import Lesson, LessonStatus
from app.models.usage_counter import UsageCounter, UsageResource
from app.models.user import User
from app.services import billing_service, quota_service
from tests.factories import make_course, make_lesson, make_module

pytestmark = pytest.mark.integration


def _capture_apply_async(
    monkeypatch: pytest.MonkeyPatch, task_obj: Any
) -> list[dict[str, Any]]:
    """Replace task.apply_async with a recorder that returns a fake AsyncResult."""
    calls: list[dict[str, Any]] = []

    class _Fake:
        id = "task-xyz"

    def _fake(*args: Any, **kwargs: Any) -> _Fake:
        calls.append({"args": args, "kwargs": kwargs})
        return _Fake()

    monkeypatch.setattr(task_obj, "apply_async", _fake)
    return calls


async def _set_plan(db: AsyncSession, user_id: Any, plan: CreditPlan) -> None:
    account = await billing_service.get_or_create_account(db, user_id)
    account.plan = plan
    await db.commit()


async def _counter(db: AsyncSession, user_id: Any, resource: UsageResource) -> int | None:
    return await db.scalar(
        select(UsageCounter.count).where(
            UsageCounter.user_id == user_id,
            UsageCounter.period_key == quota_service._current_period_key(),
            UsageCounter.resource == resource,
        )
    )


# ── generate-video ───────────────────────────────────────────────────────────


async def test_generate_video_free_enqueues_low_priority_and_increments(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import video_pipeline as vp

    calls = _capture_apply_async(monkeypatch, vp.generate_video_lesson)

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/generate-video",
        json={"pptx_path": "pptx/x.pptx", "voice": "xenia"},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert len(calls) == 1
    assert calls[0]["kwargs"]["queue"] == "video"
    assert calls[0]["kwargs"]["priority"] == TIER_PRIORITY["free"]
    assert await _counter(db_session, teacher_user.id, UsageResource.video) == 1


async def test_generate_video_paid_enqueues_higher_priority(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _set_plan(db_session, teacher_user.id, CreditPlan.pro)

    from app.tasks import video_pipeline as vp

    calls = _capture_apply_async(monkeypatch, vp.generate_video_lesson)

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/generate-video",
        json={"pptx_path": "pptx/x.pptx", "voice": "xenia"},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert calls[0]["kwargs"]["priority"] == TIER_PRIORITY["paid"]
    # paid is a smaller number (higher priority) than free.
    assert TIER_PRIORITY["paid"] < TIER_PRIORITY["free"]


async def test_generate_video_quota_exhausted_returns_402(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(TIER_QUOTAS["free"], "monthly_video", 2)

    from app.tasks import video_pipeline as vp

    calls = _capture_apply_async(monkeypatch, vp.generate_video_lesson)

    # Pre-seed the counter at the limit for this month.
    db_session.add(
        UsageCounter(
            user_id=teacher_user.id,
            period_key=quota_service._current_period_key(),
            resource=UsageResource.video,
            count=2,
        )
    )
    await db_session.commit()

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/generate-video",
        json={"pptx_path": "pptx/x.pptx", "voice": "xenia"},
        cookies=teacher_token,
    )
    assert resp.status_code == 402
    detail = resp.json()["detail"]
    assert detail["code"] == "quota_exceeded"
    assert detail["resource"] == "video"
    assert detail["limit"] == 2
    assert detail["used"] == 2
    # No enqueue, and the counter is untouched.
    assert calls == []
    assert await _counter(db_session, teacher_user.id, UsageResource.video) == 2


async def test_generate_video_concurrency_returns_429(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(TIER_QUOTAS["free"], "max_concurrent_jobs", 1)

    from app.tasks import video_pipeline as vp

    calls = _capture_apply_async(monkeypatch, vp.generate_video_lesson)

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    await make_lesson(db_session, module, status=LessonStatus.processing)  # 1 active
    target = await make_lesson(
        db_session, module, pptx_path="pptx/x.pptx", status=LessonStatus.ready_for_edit
    )

    resp = await client.post(
        f"/api/v1/lessons/{target.id}/generate-video",
        json={"pptx_path": "pptx/x.pptx", "voice": "xenia"},
        cookies=teacher_token,
    )
    assert resp.status_code == 429
    detail = resp.json()["detail"]
    assert detail["code"] == "concurrency_limit"
    assert detail["limit"] == 1
    assert detail["active"] == 1
    assert resp.headers.get("retry-after")
    # No enqueue and no monthly increment.
    assert calls == []
    assert await _counter(db_session, teacher_user.id, UsageResource.video) is None


# ── analyze ──────────────────────────────────────────────────────────────────


async def test_analyze_free_enqueues_with_priority_and_increments(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import vision_pipeline as vp

    calls = _capture_apply_async(monkeypatch, vp.analyze_presentation_task)

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/analyze", cookies=teacher_token)
    assert resp.status_code == 200
    assert calls[0]["kwargs"]["queue"] == "vision"
    assert calls[0]["kwargs"]["priority"] == TIER_PRIORITY["free"]
    assert await _counter(db_session, teacher_user.id, UsageResource.vision) == 1


async def test_analyze_quota_exhausted_returns_402_and_keeps_lesson_draft(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(TIER_QUOTAS["free"], "monthly_vision", 1)

    from app.tasks import vision_pipeline as vp

    calls = _capture_apply_async(monkeypatch, vp.analyze_presentation_task)

    db_session.add(
        UsageCounter(
            user_id=teacher_user.id,
            period_key=quota_service._current_period_key(),
            resource=UsageResource.vision,
            count=1,
        )
    )
    await db_session.commit()

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/analyze", cookies=teacher_token)
    assert resp.status_code == 402
    assert resp.json()["detail"]["code"] == "quota_exceeded"
    assert resp.json()["detail"]["resource"] == "vision"
    assert calls == []

    # The status flip happens only after the reservation succeeds — rejection
    # must leave the lesson in its original (draft) state.
    lesson_id = lesson.id
    db_session.expire_all()
    refreshed = await db_session.get(Lesson, lesson_id)
    assert refreshed is not None
    assert refreshed.status == LessonStatus.draft


# ── quota status ──────────────────────────────────────────────────────────────


async def test_quota_status_endpoint_reflects_usage(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    await quota_service.reserve(db_session, teacher_user.id, UsageResource.video)

    resp = await client.get("/api/v1/quota", cookies=teacher_token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["tier"] == "free"
    assert body["active_jobs"] == 0
    assert body["max_concurrent_jobs"] == TIER_QUOTAS["free"]["max_concurrent_jobs"]
    assert body["video"]["used"] == 1
    assert body["video"]["limit"] == TIER_QUOTAS["free"]["monthly_video"]
    assert body["video"]["remaining"] == TIER_QUOTAS["free"]["monthly_video"] - 1
    assert body["vision"]["used"] == 0
