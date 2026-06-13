"""Pre-prod hardening: the analysis / quiz-generation status endpoints derive
their terminal state from the DB (lesson.status / persisted quiz state), not
from the Celery result backend (Redis). A task_id absent from the (empty,
in-memory) result backend resolves to AsyncResult.status == PENDING; the
endpoints must ignore that and answer from the DB so they survive a Redis
restart instead of hanging the UI on a finished job.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import Lesson, LessonStatus
from app.models.user import User
from tests.factories import (
    make_course,
    make_lesson,
    make_module,
    make_quiz,
    make_quiz_question,
)

pytestmark = pytest.mark.integration

# Not present in the empty in-memory result backend → AsyncResult(this) is PENDING.
_UNKNOWN_TASK = "task-not-in-result-backend"


async def _owned_lesson(
    db: AsyncSession, teacher: User, **lesson_kw: object
) -> Lesson:
    course = await make_course(db, owner=teacher)
    module = await make_module(db, course)
    return await make_lesson(db, module, **lesson_kw)


@pytest.mark.parametrize(
    ("lesson_status", "expected"),
    [
        (LessonStatus.analyzing, "PROGRESS"),
        (LessonStatus.ready_for_edit, "SUCCESS"),
        (LessonStatus.error, "FAILURE"),
        (LessonStatus.cancelled, "REVOKED"),
    ],
)
async def test_analysis_status_from_lesson_status(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    lesson_status: LessonStatus,
    expected: str,
) -> None:
    lesson = await _owned_lesson(db_session, teacher_user, status=lesson_status)
    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/analysis-status/{_UNKNOWN_TASK}",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == expected


async def test_quiz_generation_status_success_from_db(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    lesson = await _owned_lesson(
        db_session, teacher_user, status=LessonStatus.published
    )
    quiz = await make_quiz(db_session, lesson)  # generation_task_id is None (done)
    await make_quiz_question(db_session, quiz)  # one current question → SUCCESS

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/quiz/generation-status/{_UNKNOWN_TASK}",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "SUCCESS"


async def test_quiz_generation_status_in_progress_uses_result_backend(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    lesson = await _owned_lesson(
        db_session, teacher_user, status=LessonStatus.published
    )
    # generation_task_id == the polled task → still running → defer to the
    # result backend (empty here → PENDING), not a DB shortcut.
    await make_quiz(db_session, lesson, generation_task_id=_UNKNOWN_TASK)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/quiz/generation-status/{_UNKNOWN_TASK}",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "PENDING"
