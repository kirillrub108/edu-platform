"""End-to-end lesson routes — create, update, script, generate-video."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import Lesson, LessonStatus
from app.models.user import User
from tests.factories import make_course, make_lesson, make_module

pytestmark = pytest.mark.integration


async def test_create_lesson_returns_201(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)

    resp = await client.post(
        "/api/v1/lessons/",
        json={"title": "Lesson A", "module_id": str(module.id)},
        headers=teacher_token,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Lesson A"
    assert body["status"] == "draft"


async def test_update_lesson_script(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.put(
        f"/api/v1/lessons/{lesson.id}/script",
        json={"script": "Hello narration."},
        headers=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json()["script"] == "Hello narration."


async def test_generate_video_without_pptx_returns_400(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)  # no pptx_path

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/generate-video",
        json={},
        headers=teacher_token,
    )
    assert resp.status_code == 400
    assert "pptx_path" in resp.json()["detail"].lower()


async def test_generate_video_with_pptx_enqueues_task(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, pptx_path="pptx/x.pptx")

    # Patch apply_async on the task object the router imports.
    from app.tasks import video_pipeline as vp

    fake_task_id = "task-abc-123"

    class _Fake:
        id = fake_task_id

    def _fake_apply_async(*args: Any, **kwargs: Any) -> _Fake:
        return _Fake()

    monkeypatch.setattr(vp.generate_video_lesson, "apply_async", _fake_apply_async)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/generate-video",
        json={"pptx_path": "pptx/x.pptx", "voice": "xenia"},
        headers=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == fake_task_id
    assert body["lesson_id"] == str(lesson.id)

    # Persisted on the lesson for resume-after-refresh polling.
    lesson_id = lesson.id  # snapshot before expire_all so the next get()
    db_session.expire_all()  # call doesn't trigger a sync lazy-load.
    refreshed = await db_session.get(Lesson, lesson_id)
    assert refreshed is not None
    assert refreshed.video_task_id == fake_task_id


@pytest.mark.parametrize(
    "lesson_status, expected_celery_status",
    [
        (LessonStatus.draft, "PENDING"),
        (LessonStatus.processing, "PROGRESS"),
        (LessonStatus.published, "SUCCESS"),
        (LessonStatus.error, "FAILURE"),
    ],
)
async def test_task_status_maps_lesson_status(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    lesson_status: LessonStatus,
    expected_celery_status: str,
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, status=lesson_status)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/task-status/some-task-id",
        headers=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == expected_celery_status
