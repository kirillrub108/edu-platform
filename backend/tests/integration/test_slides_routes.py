"""End-to-end slides routes (analyze / list / patch / regenerate)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import Lesson
from app.models.user import User, UserRole
from app.services.auth_service import hash_password
from tests.factories import (
    make_course,
    make_lesson,
    make_module,
    make_slide_text,
)

pytestmark = pytest.mark.integration


async def test_analyze_enqueues_vision_task_and_persists_id(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")

    from app.routers import slides as slides_router
    from app.tasks import vision_pipeline as vp

    monkeypatch.setattr(slides_router, "count_source_slides", lambda _p: 5)

    class _Fake:
        id = "vision-task-1"

    monkeypatch.setattr(
        vp.analyze_presentation_task, "apply_async", lambda *a, **k: _Fake()
    )

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/analyze", cookies=teacher_token
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == "vision-task-1"
    # Fresh free account with trial slots left → analysis rides for free.
    assert body["billed_via"] == "trial"

    lesson_id = lesson.id  # snapshot — expire_all() expires `lesson`, and
    db_session.expire_all()  # reading `lesson.id` afterwards would trigger a
    refreshed = await db_session.get(Lesson, lesson_id)  # sync lazy-load.
    assert refreshed is not None
    assert refreshed.analyze_task_id == "vision-task-1"


async def test_analyze_without_pptx_returns_400(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)  # no pptx_path

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/analyze", cookies=teacher_token
    )
    assert resp.status_code == 400


async def test_list_slides_empty(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/slides", cookies=teacher_token
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["slides"] == []


async def test_list_slides_returns_image_url(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    await make_slide_text(db_session, lesson, slide_number=1)
    await make_slide_text(db_session, lesson, slide_number=2)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/slides", cookies=teacher_token
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    for s in body["slides"]:
        assert s["image_url"] is not None
        assert "/files/" in s["image_url"]


async def test_patch_slide_updates_edited_text(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    row = await make_slide_text(db_session, lesson, slide_number=1)

    resp = await client.patch(
        f"/api/v1/lessons/{lesson.id}/slides/{row.id}",
        json={"edited_text": "Manually edited"},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json()["edited_text"] == "Manually edited"
    assert resp.json()["is_edited"] is True


async def test_regenerate_uses_vision_mock(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    mock_vision: dict[str, Any],
    tmp_path: Any,
) -> None:
    """Mock vision service so no LLM is hit. Image existence is checked via
    storage_service.get_full_path — point STORAGE_PATH to tmp_path here."""
    from app.services import billing_service

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    # image_path stays as a string; vision service is fully stubbed so the
    # actual file doesn't need to exist for our mocked analyze_slide.
    row = await make_slide_text(db_session, lesson, slide_number=1)
    mock_vision["analyze_return"] = "Regenerated narration"
    # Slide regen costs 1 CR and free accounts start at zero now.
    await billing_service.grant_credits(db_session, teacher_user.id, 5, "seed")

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/slides/{row.id}/regenerate",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["generated_text"] == "Regenerated narration"
    assert body["edited_text"] is None


async def test_other_teacher_cannot_list_slides(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
) -> None:
    # Lesson owned by a *different* teacher
    other = User(
        email="z@e.com",
        hashed_password=hash_password("password123"),
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    course = await make_course(db_session, owner=other)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    from app.services.auth_service import create_access_token
    from tests.conftest import _TEST_CSRF
    token, _, _ = create_access_token(teacher_user)
    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/slides",
        cookies={"access_token": token, "csrf_token": _TEST_CSRF},
    )
    assert resp.status_code == 404


async def test_cancel_analysis_releases_reserved_credits(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cancelling a still-queued vision task must fully release the router-side
    reservation identified by the lesson's billing_ref."""
    from app.constants import CREDIT_WEIGHTS
    from app.models.credit import CreditOperation
    from app.models.lesson import LessonStatus
    from app.services import billing_service

    monkeypatch.setattr("celery.result.AsyncResult.revoke", lambda self, *a, **k: None)

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    amount = CREDIT_WEIGHTS["vision_analyze"]
    billing_ref = "ref-vis-cancel"
    lesson = await make_lesson(
        db_session,
        module,
        status=LessonStatus.analyzing,
        analyze_task_id="vis-task-1",
        billed_via="credits",
        billing_ref=billing_ref,
        credit_estimate=amount,
    )

    await billing_service.grant_credits(db_session, teacher_user.id, 50, "seed")
    ok = await billing_service.reserve_credits(
        db_session, teacher_user.id, amount, billing_ref, CreditOperation.VISION_ANALYZE
    )
    assert ok
    before = await billing_service.get_balance(db_session, teacher_user.id)
    assert before["reserved"] == amount

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/analysis-cancel", cookies=teacher_token
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    after = await billing_service.get_balance(db_session, teacher_user.id)
    assert after["reserved"] == 0
    assert after["available"] == before["available"] + amount

    history = await billing_service.get_transaction_history(db_session, teacher_user.id)
    releases = [t for t in history if t.operation == CreditOperation.RELEASE]
    assert len(releases) == 1
    assert releases[0].ref_id == billing_ref
