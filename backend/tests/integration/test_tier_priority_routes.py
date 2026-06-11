"""The enqueue routes (generate-video, analyze) pass the tier-derived Celery
priority to apply_async — paid plans get a higher priority (lower number) than
free. Broker mocked."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TIER_PRIORITY
from app.models.credit import CreditPlan
from app.models.user import User
from app.services import billing_service
from tests.factories import make_course, make_lesson, make_module

pytestmark = pytest.mark.integration


def _capture_apply_async(monkeypatch: pytest.MonkeyPatch, task_obj: Any) -> list[dict[str, Any]]:
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


async def test_generate_video_free_uses_low_priority(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import lessons as lessons_router
    from app.tasks import video_pipeline as vp

    monkeypatch.setattr(lessons_router, "count_source_slides", lambda _p: 5)
    calls = _capture_apply_async(monkeypatch, vp.generate_video_lesson)

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")

    # Fresh free account: the launch is covered by a trial slot (no credits).
    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/generate-video",
        json={"pptx_path": "pptx/x.pptx", "voice": "nova"},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert calls[0]["kwargs"]["queue"] == "video"
    assert calls[0]["kwargs"]["priority"] == TIER_PRIORITY["free"]


async def test_generate_video_paid_uses_higher_priority(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _set_plan(db_session, teacher_user.id, CreditPlan.pro)
    # Paid plans have no trial — fund the reservation.
    await billing_service.grant_credits(db_session, teacher_user.id, 100, "seed")

    from app.routers import lessons as lessons_router
    from app.tasks import video_pipeline as vp

    monkeypatch.setattr(lessons_router, "count_source_slides", lambda _p: 5)
    calls = _capture_apply_async(monkeypatch, vp.generate_video_lesson)

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/generate-video",
        json={"pptx_path": "pptx/x.pptx", "voice": "nova"},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert calls[0]["kwargs"]["priority"] == TIER_PRIORITY["paid"]
    assert TIER_PRIORITY["paid"] < TIER_PRIORITY["free"]


async def test_analyze_free_uses_low_priority(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import slides as slides_router
    from app.tasks import vision_pipeline as vp

    monkeypatch.setattr(slides_router, "count_source_slides", lambda _p: 5)
    calls = _capture_apply_async(monkeypatch, vp.analyze_presentation_task)

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")

    resp = await client.post(f"/api/v1/lessons/{lesson.id}/analyze", cookies=teacher_token)
    assert resp.status_code == 200
    assert calls[0]["kwargs"]["queue"] == "vision"
    assert calls[0]["kwargs"]["priority"] == TIER_PRIORITY["free"]
