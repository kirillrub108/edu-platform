"""Integration tests for the teacher quiz analytics endpoints.

GET /api/v1/teacher/analytics/summary
GET /api/v1/teacher/analytics/quiz-lessons
GET /api/v1/teacher/analytics/quiz-lessons/{lesson_id}/submissions
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import ContentType, LessonStatus
from app.models.quiz import AttemptStatus, Quiz, QuizAttempt, QuizStatus
from app.models.user import User, UserRole
from app.services.auth_service import create_access_token, hash_password
from tests.conftest import _TEST_CSRF
from tests.factories import (
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
    make_quiz,
    make_quiz_attempt,
)

pytestmark = pytest.mark.integration


def _cookies_for(user: User) -> dict[str, str]:
    token, _jti, _exp = create_access_token(user)
    return {"access_token": token, "csrf_token": _TEST_CSRF}


async def _make_student(db: AsyncSession, email: str | None = None) -> User:
    user = User(
        email=email or f"st-{uuid.uuid4().hex[:8]}@e.com",
        hashed_password=hash_password("pass-1234"),
        full_name="Student X",
        role=UserRole.student,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_quiz_lesson(
    db: AsyncSession,
    teacher: User,
    *,
    title: str = "Q",
    content_type: ContentType = ContentType.video,
):
    """Lesson with an attached Quiz. content_type defaults to video to mirror
    real usage — the UI lets video lessons carry a quiz tab."""
    course = await make_course(db, teacher, is_published=True, title=f"C {title}")
    module = await make_module(db, course, title=f"M {title}")
    lesson = await make_lesson(
        db,
        module,
        title=title,
        content_type=content_type,
        status=LessonStatus.published,
    )
    quiz = await make_quiz(db, lesson, published=True)
    return course, module, lesson, quiz


async def _graded_attempt(
    db: AsyncSession,
    quiz: Quiz,
    student: User,
    *,
    score: float,
    submitted_at: datetime,
    attempt_number: int = 1,
) -> QuizAttempt:
    threshold = float(quiz.pass_threshold)
    attempt = await make_quiz_attempt(
        db, quiz, student,
        status=AttemptStatus.graded,
        attempt_number=attempt_number,
        score=Decimal(str(score)),
        passed=score >= threshold,
        submitted_at=submitted_at,
        graded_at=submitted_at,
    )
    return attempt


# ── /summary ────────────────────────────────────────────────────────────────


async def test_summary_empty_for_teacher_without_quizzes(
    client: AsyncClient,
    teacher_token: dict[str, str],
) -> None:
    resp = await client.get(
        "/api/v1/teacher/analytics/summary", cookies=teacher_token
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "total_quiz_lessons": 0,
        "total_attempts": 0,
        "avg_score": None,
        "pass_rate": None,
        "recent_submissions": [],
    }


async def test_summary_counts_failed_attempts(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    # Regression for the original report: a student took the quiz 3 times
    # and FAILED all three. The teacher still needs to see those attempts.
    course, _, lesson, quiz = await _make_quiz_lesson(db_session, teacher_user)
    student = await _make_student(db_session)
    await make_enrollment(db_session, student, course)
    await _graded_attempt(
        db_session, quiz, student, score=0.1,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        attempt_number=1,
    )
    await _graded_attempt(
        db_session, quiz, student, score=0.3,
        submitted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        attempt_number=2,
    )

    resp = await client.get(
        "/api/v1/teacher/analytics/summary", cookies=teacher_token
    )
    body = resp.json()
    assert body["total_quiz_lessons"] == 1
    assert body["total_attempts"] == 2
    assert body["avg_score"] == pytest.approx((0.1 + 0.3) / 2, rel=1e-3)
    assert body["pass_rate"] == pytest.approx(0.0)
    # recent_submissions collapses to best per (student, quiz) → score 0.3.
    assert len(body["recent_submissions"]) == 1
    assert body["recent_submissions"][0]["score"] == pytest.approx(0.3)
    assert body["recent_submissions"][0]["passed"] is False


async def test_summary_aggregates_mixed_outcomes(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course, _, lesson, quiz = await _make_quiz_lesson(db_session, teacher_user, title="Alg")
    s1 = await _make_student(db_session, "p1@e.com")
    s2 = await _make_student(db_session, "p2@e.com")
    s3 = await _make_student(db_session, "f1@e.com")
    for s in (s1, s2, s3):
        await make_enrollment(db_session, s, course)
    await _graded_attempt(
        db_session, quiz, s1, score=0.9,
        submitted_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )
    await _graded_attempt(
        db_session, quiz, s2, score=0.6,
        submitted_at=datetime(2026, 1, 6, tzinfo=timezone.utc),
    )
    await _graded_attempt(
        db_session, quiz, s3, score=0.4,
        submitted_at=datetime(2026, 1, 7, tzinfo=timezone.utc),
    )

    resp = await client.get(
        "/api/v1/teacher/analytics/summary", cookies=teacher_token
    )
    body = resp.json()
    assert body["total_attempts"] == 3
    assert body["avg_score"] == pytest.approx((0.9 + 0.6 + 0.4) / 3, rel=1e-3)
    assert body["pass_rate"] == pytest.approx(2 / 3, rel=1e-3)


async def test_summary_isolates_per_teacher(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    other = User(
        email=f"t2-{uuid.uuid4().hex[:6]}@e.com",
        hashed_password=hash_password("pass-1234"),
        full_name="T2",
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    course, _, lesson, quiz = await _make_quiz_lesson(db_session, other)
    student = await _make_student(db_session)
    await make_enrollment(db_session, student, course)
    await _graded_attempt(
        db_session, quiz, student, score=0.95,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    resp = await client.get(
        "/api/v1/teacher/analytics/summary", cookies=teacher_token
    )
    body = resp.json()
    assert body["total_quiz_lessons"] == 0
    assert body["total_attempts"] == 0


async def test_summary_ignores_in_progress_attempts(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course, _, lesson, quiz = await _make_quiz_lesson(db_session, teacher_user)
    student = await _make_student(db_session)
    await make_enrollment(db_session, student, course)
    # In-progress attempt with no score must be ignored.
    await make_quiz_attempt(
        db_session, quiz, student,
        status=AttemptStatus.in_progress,
        attempt_number=1,
        score=None,
        passed=None,
    )

    resp = await client.get(
        "/api/v1/teacher/analytics/summary", cookies=teacher_token
    )
    body = resp.json()
    assert body["total_quiz_lessons"] == 1
    assert body["total_attempts"] == 0


# ── /quiz-lessons ───────────────────────────────────────────────────────────


async def test_quiz_lessons_includes_lesson_without_attempts(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson, _ = await _make_quiz_lesson(db_session, teacher_user, title="Lonely")
    resp = await client.get(
        "/api/v1/teacher/analytics/quiz-lessons", cookies=teacher_token
    )
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["lesson_id"] == str(lesson.id)
    assert item["attempts_count"] == 0
    assert item["students_count"] == 0
    assert item["avg_score"] is None
    assert item["pass_rate"] is None
    assert item["last_attempt_at"] is None


async def test_quiz_lessons_skips_lessons_without_quiz(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, teacher_user, is_published=True)
    module = await make_module(db_session, course)
    # Plain video lesson, no quiz attached → not in the report.
    await make_lesson(
        db_session, module, content_type=ContentType.video,
        status=LessonStatus.published,
    )
    resp = await client.get(
        "/api/v1/teacher/analytics/quiz-lessons", cookies=teacher_token
    )
    assert resp.json()["total"] == 0


async def test_quiz_lessons_filter_by_course(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course_a, _, _, _ = await _make_quiz_lesson(db_session, teacher_user, title="A")
    course_b, _, lesson_b, _ = await _make_quiz_lesson(db_session, teacher_user, title="B")
    resp = await client.get(
        f"/api/v1/teacher/analytics/quiz-lessons?course_id={course_b.id}",
        cookies=teacher_token,
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["lesson_id"] == str(lesson_b.id)


async def test_quiz_lessons_search_case_insensitive(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    await _make_quiz_lesson(db_session, teacher_user, title="Linear Algebra")
    await _make_quiz_lesson(db_session, teacher_user, title="Calculus")
    resp = await client.get(
        "/api/v1/teacher/analytics/quiz-lessons?search=algebra",
        cookies=teacher_token,
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["lesson_title"] == "Linear Algebra"


async def test_quiz_lessons_search_empty_returns_all(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    await _make_quiz_lesson(db_session, teacher_user, title="L1")
    await _make_quiz_lesson(db_session, teacher_user, title="L2")
    resp = await client.get(
        "/api/v1/teacher/analytics/quiz-lessons?search=",
        cookies=teacher_token,
    )
    assert resp.json()["total"] == 2


async def test_quiz_lessons_sort_by_avg_score_desc(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course_h, _, lesson_h, quiz_h = await _make_quiz_lesson(db_session, teacher_user, title="High")
    course_l, _, lesson_l, quiz_l = await _make_quiz_lesson(db_session, teacher_user, title="Low")
    student = await _make_student(db_session)
    await make_enrollment(db_session, student, course_h)
    await make_enrollment(db_session, student, course_l)
    await _graded_attempt(
        db_session, quiz_h, student, score=0.9,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    await _graded_attempt(
        db_session, quiz_l, student, score=0.2,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    resp = await client.get(
        "/api/v1/teacher/analytics/quiz-lessons?sort=avg_score&order=desc",
        cookies=teacher_token,
    )
    ids = [it["lesson_id"] for it in resp.json()["items"]]
    assert ids[0] == str(lesson_h.id)


async def test_quiz_lessons_invalid_sort_422(
    client: AsyncClient,
    teacher_token: dict[str, str],
) -> None:
    resp = await client.get(
        "/api/v1/teacher/analytics/quiz-lessons?sort=bogus",
        cookies=teacher_token,
    )
    assert resp.status_code == 422


async def test_quiz_lessons_page_size_over_limit_422(
    client: AsyncClient,
    teacher_token: dict[str, str],
) -> None:
    resp = await client.get(
        "/api/v1/teacher/analytics/quiz-lessons?page_size=200",
        cookies=teacher_token,
    )
    assert resp.status_code == 422


async def test_quiz_lessons_pagination(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    for i in range(5):
        await _make_quiz_lesson(db_session, teacher_user, title=f"L{i}")
    resp = await client.get(
        "/api/v1/teacher/analytics/quiz-lessons?page=2&page_size=2",
        cookies=teacher_token,
    )
    body = resp.json()
    assert body["total"] == 5
    assert body["page"] == 2
    assert len(body["items"]) == 2


# ── /submissions ────────────────────────────────────────────────────────────


async def test_submissions_returns_best_attempt_per_student(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course, _, lesson, quiz = await _make_quiz_lesson(db_session, teacher_user)
    student = await _make_student(db_session, "x@e.com")
    await make_enrollment(db_session, student, course)
    await _graded_attempt(
        db_session, quiz, student, score=0.3,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        attempt_number=1,
    )
    await _graded_attempt(
        db_session, quiz, student, score=0.8,
        submitted_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        attempt_number=2,
    )

    resp = await client.get(
        f"/api/v1/teacher/analytics/quiz-lessons/{lesson.id}/submissions",
        cookies=teacher_token,
    )
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["score"] == pytest.approx(0.8)
    assert body["items"][0]["passed"] is True


async def test_submissions_includes_failed_attempts(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    # Direct regression for the original report.
    course, _, lesson, quiz = await _make_quiz_lesson(db_session, teacher_user)
    student = await _make_student(db_session, "fail@e.com")
    await make_enrollment(db_session, student, course)
    await _graded_attempt(
        db_session, quiz, student, score=0.2,
        submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    resp = await client.get(
        f"/api/v1/teacher/analytics/quiz-lessons/{lesson.id}/submissions",
        cookies=teacher_token,
    )
    body = resp.json()
    assert body["total"] == 1
    item = body["items"][0]
    assert item["student_email"] == "fail@e.com"
    assert item["passed"] is False
    assert item["score"] == pytest.approx(0.2)


async def test_submissions_404_for_other_teacher(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
) -> None:
    course, _, lesson, _ = await _make_quiz_lesson(db_session, teacher_user)
    other = User(
        email=f"t3-{uuid.uuid4().hex[:6]}@e.com",
        hashed_password=hash_password("pass-1234"),
        full_name="T3",
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    resp = await client.get(
        f"/api/v1/teacher/analytics/quiz-lessons/{lesson.id}/submissions",
        cookies=_cookies_for(other),
    )
    assert resp.status_code == 404


async def test_submissions_404_for_lesson_without_quiz(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(
        db_session, module, content_type=ContentType.video,
        status=LessonStatus.published,
    )
    resp = await client.get(
        f"/api/v1/teacher/analytics/quiz-lessons/{lesson.id}/submissions",
        cookies=teacher_token,
    )
    assert resp.status_code == 404


async def test_submissions_404_for_missing_lesson(
    client: AsyncClient,
    teacher_token: dict[str, str],
) -> None:
    resp = await client.get(
        f"/api/v1/teacher/analytics/quiz-lessons/{uuid.uuid4()}/submissions",
        cookies=teacher_token,
    )
    assert resp.status_code == 404


async def test_summary_forbidden_for_student(
    client: AsyncClient,
    student_token: dict[str, str],
) -> None:
    resp = await client.get(
        "/api/v1/teacher/analytics/summary", cookies=student_token
    )
    assert resp.status_code == 403
