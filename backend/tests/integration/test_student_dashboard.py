"""Student cabinet dashboard aggregate — GET /api/v1/students/dashboard."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import ContentType, LessonStatus
from app.models.quiz import AttemptStatus
from app.models.user import User
from tests.factories import (
    make_assignment,
    make_assignment_submission,
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
    make_quiz,
    make_quiz_attempt,
)

pytestmark = pytest.mark.integration


async def test_dashboard_unauthorized_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/students/dashboard")
    assert resp.status_code == 401


async def test_dashboard_empty_for_new_student(
    client: AsyncClient,
    student_token: dict[str, str],
) -> None:
    resp = await client.get("/api/v1/students/dashboard", cookies=student_token)
    assert resp.status_code == 200
    assert resp.json() == {
        "enrolled_courses": 0,
        "completed_assignments": 0,
        "average_score": None,
        "nearest_deadline": None,
    }


async def test_dashboard_aggregates_student_activity(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course)
    enrollment = await make_enrollment(db_session, student_user, course)

    # A graded quiz attempt → drives the average score (0.8 → 80.0%).
    quiz_lesson = await make_lesson(
        db_session, module, content_type=ContentType.quiz, status=LessonStatus.published
    )
    quiz = await make_quiz(db_session, quiz_lesson, published=True)
    await make_quiz_attempt(
        db_session, quiz, student_user, status=AttemptStatus.graded, score=0.8
    )

    # A submitted assignment with a future deadline → completed count + nearest deadline.
    assignment_lesson = await make_lesson(
        db_session, module, status=LessonStatus.published
    )
    due = datetime.now(timezone.utc) + timedelta(days=3)
    assignment = await make_assignment(
        db_session, assignment_lesson, published=True, title="Эссе", due_at=due
    )
    await make_assignment_submission(db_session, assignment, enrollment)

    resp = await client.get("/api/v1/students/dashboard", cookies=student_token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["enrolled_courses"] == 1
    assert body["completed_assignments"] == 1
    assert body["average_score"] == 80.0
    assert body["nearest_deadline"] is not None
    assert body["nearest_deadline"]["title"] == "Эссе"
    assert body["nearest_deadline"]["assignment_id"] == str(assignment.id)


# ── Cabinet list endpoints: smoke-test that the joins compile + execute ──────


@pytest.mark.parametrize("path", ["/quizzes", "/results", "/assignments"])
async def test_cabinet_lists_unauthorized_returns_401(
    client: AsyncClient, path: str
) -> None:
    resp = await client.get(f"/api/v1/students{path}")
    assert resp.status_code == 401


@pytest.mark.parametrize("path", ["/quizzes", "/results", "/assignments"])
async def test_cabinet_lists_empty_for_new_student(
    client: AsyncClient, student_token: dict[str, str], path: str
) -> None:
    resp = await client.get(f"/api/v1/students{path}", cookies=student_token)
    assert resp.status_code == 200
    assert resp.json() == []
