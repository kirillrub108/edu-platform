"""Lifetime free-account trial: 2 lectures + 2 quizzes, caps, exhaustion → 402."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import TRIAL_LECTURES, TRIAL_MAX_SLIDES, TRIAL_QUIZZES
from app.models.user import User
from app.services import billing_service, quota_service
from tests.factories import make_course, make_lesson, make_module

pytestmark = pytest.mark.integration


def _mock_video_enqueue(monkeypatch: pytest.MonkeyPatch, slides: int = 5) -> None:
    from app.routers import lessons as lessons_router
    from app.tasks import video_pipeline as vp

    class _Fake:
        id = "task-trial"

    monkeypatch.setattr(lessons_router, "count_source_slides", lambda _p: slides)
    monkeypatch.setattr(vp.generate_video_lesson, "apply_async", lambda *a, **k: _Fake())


async def _launch_video(
    client: AsyncClient, lesson_id: Any, teacher_token: dict[str, str]
) -> Any:
    return await client.post(
        f"/api/v1/lessons/{lesson_id}/generate-video",
        json={"pptx_path": "pptx/x.pptx", "voice": "nova"},
        cookies=teacher_token,
    )


async def test_third_lecture_returns_trial_exhausted(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Free account, no credits: lectures 1–2 ride the trial, the 3rd gets a
    machine-readable 402 trial_exhausted; after buying credits it goes through."""
    # Snapshot: service-level rollbacks (the 402 path) expire ORM instances,
    # and reading teacher_user.id afterwards would raise MissingGreenlet.
    uid = teacher_user.id
    _mock_video_enqueue(monkeypatch)
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")
    lesson_id = lesson.id  # snapshot — the 402 rollback expires the instance

    for attempt in range(TRIAL_LECTURES):
        resp = await _launch_video(client, lesson_id, teacher_token)
        assert resp.status_code == 200, f"trial launch {attempt + 1} failed"
        assert resp.json()["billed_via"] == "trial"

    third = await _launch_video(client, lesson_id, teacher_token)
    assert third.status_code == 402
    detail = third.json()["detail"]
    assert detail["code"] == "trial_exhausted"
    assert detail["limit"] == TRIAL_LECTURES
    assert detail["used"] == TRIAL_LECTURES

    # Purchased credits unblock the operation (billed via credits now).
    await billing_service.grant_credits(db_session, uid, 100, "purchase")
    fourth = await _launch_video(client, lesson_id, teacher_token)
    assert fourth.status_code == 200
    assert fourth.json()["billed_via"] == "credits"
    balance = await billing_service.get_balance(db_session, uid)
    assert balance["reserved"] == fourth.json()["credit_estimate"]


async def test_trial_caps_route_to_credits(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lecture above the trial slide cap can't use a slot — with no credits
    that's an insufficient_credits 402, and the trial stays untouched."""
    uid = teacher_user.id  # snapshot before the 402 rollback expires the instance
    _mock_video_enqueue(monkeypatch, slides=TRIAL_MAX_SLIDES + 5)
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")

    resp = await _launch_video(client, lesson.id, teacher_token)
    assert resp.status_code == 402
    detail = resp.json()["detail"]
    assert detail["code"] == "insufficient_credits"
    assert detail["required"] > 0

    state = await quota_service.get_trial_state(db_session, uid)
    assert state["lectures_used"] == 0


async def test_third_quiz_returns_trial_exhausted(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.tasks import quiz_pipeline as qp

    captured: list[dict] = []

    class _Fake:
        id = "quiz-task-1"

    def _fake_apply_async(*args: Any, **kwargs: Any) -> _Fake:
        captured.append(kwargs)
        return _Fake()

    monkeypatch.setattr(qp.generate_quiz_task, "apply_async", _fake_apply_async)

    uid = teacher_user.id  # snapshot before the 402 rollback expires the instance
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)

    for attempt in range(TRIAL_QUIZZES):
        lesson = await make_lesson(
            db_session, module, script="Material long enough to build a quiz from."
        )
        resp = await client.post(
            f"/api/v1/lessons/{lesson.id}/quiz/generate",
            json={},
            cookies=teacher_token,
        )
        assert resp.status_code == 202, f"trial quiz {attempt + 1} failed"
        assert captured[-1]["kwargs"]["billed_via"] == "trial"

    lesson3 = await make_lesson(
        db_session, module, script="Material long enough to build a quiz from."
    )
    lesson3_id = lesson3.id  # snapshot — the 402 rollback expires the instance
    third = await client.post(
        f"/api/v1/lessons/{lesson3_id}/quiz/generate", json={}, cookies=teacher_token
    )
    assert third.status_code == 402
    detail = third.json()["detail"]
    assert detail["code"] == "trial_exhausted"
    assert detail["limit"] == TRIAL_QUIZZES

    # Credits unblock quiz generation at full price.
    await billing_service.grant_credits(db_session, uid, 10, "purchase")
    fourth = await client.post(
        f"/api/v1/lessons/{lesson3_id}/quiz/generate", json={}, cookies=teacher_token
    )
    assert fourth.status_code == 202
    assert captured[-1]["kwargs"]["billed_via"] == "credits"


async def test_estimate_endpoint_reports_trial_state(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import lessons as lessons_router

    monkeypatch.setattr(lessons_router, "count_source_slides", lambda _p: 5)
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(
        db_session, module, pptx_path="pptx/x.pptx", script="x" * 4500
    )

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/generation-estimate", cookies=teacher_token
    )
    assert resp.status_code == 200
    body = resp.json()
    # text mode: 2 + 5 slides + ceil(4500/3000)=2 → 9
    assert body["video"] == {"mode": "text", "slides": 5, "script_chars": 4500, "credits": 9}
    assert body["trial"]["video_trial_available"] is True
    assert body["trial"]["lectures_used"] == 0
    assert body["plan"] == "free"
    assert body["available"] == 0
    assert body["quiz_credits"] == 5
    assert body["ai_review_credits"] == 2
