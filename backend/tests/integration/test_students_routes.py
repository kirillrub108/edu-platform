"""End-to-end student routes (enroll / my-courses / complete / quiz)."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import LessonProgress
from app.models.lesson import LessonStatus
from app.models.user import User
from tests.factories import (
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
)

pytestmark = pytest.mark.integration


async def test_enroll_by_course_id_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)

    resp = await client.post(
        "/api/v1/students/enroll",
        json={"course_id": str(course.id)},
        headers=student_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["course_id"] == str(course.id)
    assert "enrollment_id" in body


async def test_enroll_repeat_returns_existing_id(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_token: dict[str, str],
) -> None:
    """The endpoint is idempotent for the same student → same course."""
    course = await make_course(db_session, owner=teacher_user, is_published=True)

    first = await client.post(
        "/api/v1/students/enroll",
        json={"course_id": str(course.id)},
        headers=student_token,
    )
    second = await client.post(
        "/api/v1/students/enroll",
        json={"course_id": str(course.id)},
        headers=student_token,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["enrollment_id"] == second.json()["enrollment_id"]


async def test_enroll_unpublished_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=False)
    resp = await client.post(
        "/api/v1/students/enroll",
        json={"course_id": str(course.id)},
        headers=student_token,
    )
    assert resp.status_code == 404


async def test_enroll_by_access_code(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(
        db_session, owner=teacher_user, is_published=True, access_code="JOINME"
    )
    resp = await client.post(
        "/api/v1/students/enroll",
        json={"access_code": "JOINME"},
        headers=student_token,
    )
    assert resp.status_code == 200
    assert resp.json()["course_id"] == str(course.id)


async def test_my_courses_filters_by_student(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    enrolled = await make_course(db_session, owner=teacher_user, is_published=True, title="Enrolled")
    other = await make_course(db_session, owner=teacher_user, is_published=True, title="Other")
    await make_enrollment(db_session, student_user, enrolled)

    resp = await client.get("/api/v1/students/my-courses", headers=student_token)
    assert resp.status_code == 200
    titles = [c["title"] for c in resp.json()]
    assert "Enrolled" in titles
    assert "Other" not in titles


async def test_complete_lesson_marks_progress(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, status=LessonStatus.published)
    await make_enrollment(db_session, student_user, course)

    resp = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/complete", headers=student_token
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["completed"] is True

    row = await db_session.scalar(
        select(LessonProgress).where(LessonProgress.lesson_id == lesson.id)
    )
    assert row is not None
    assert row.is_completed is True


@pytest.mark.parametrize(
    "score, should_complete",
    [(0.59, False), (0.6, True), (0.95, True)],
)
async def test_quiz_result_auto_completes_when_score_high(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
    score: float,
    should_complete: bool,
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, status=LessonStatus.published)
    await make_enrollment(db_session, student_user, course)

    resp = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz-result",
        json={"score": score},
        headers=student_token,
    )
    assert resp.status_code == 200
    assert resp.json()["score"] == score

    row = await db_session.scalar(
        select(LessonProgress).where(LessonProgress.lesson_id == lesson.id)
    )
    assert row is not None
    assert row.is_completed is should_complete
