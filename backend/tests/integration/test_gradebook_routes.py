"""Integration tests for gradebook endpoints.

GET  /api/v1/courses/{course_id}/gradebook
PATCH /api/v1/courses/{course_id}/progress/{progress_id}
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import ContentType, LessonStatus
from app.models.user import User
from tests.conftest import _TEST_CSRF
from tests.factories import (
    make_course,
    make_enrollment,
    make_lesson,
    make_lesson_progress,
    make_module,
)

pytestmark = pytest.mark.integration


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _make_quiz_course(db: AsyncSession, owner: User) -> tuple:
    """Published course → 1 module → 1 quiz lesson."""
    course = await make_course(db, owner, is_published=True)
    module = await make_module(db, course)
    lesson = await make_lesson(
        db,
        module,
        content_type=ContentType.quiz,
        status=LessonStatus.published,
    )
    return course, module, lesson


# ── GET /gradebook ───────────────────────────────────────────────────────────


async def test_gradebook_owner_empty_course(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)

    resp = await client.get(
        f"/api/v1/courses/{course.id}/gradebook",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["course_id"] == str(course.id)
    assert body["students"] == []


async def test_gradebook_includes_student_with_no_progress(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    course, _module, lesson = await _make_quiz_course(db_session, teacher_user)
    await make_enrollment(db_session, student_user, course)

    resp = await client.get(
        f"/api/v1/courses/{course.id}/gradebook",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["students"]) == 1
    row = body["students"][0]
    assert row["student_id"] == str(student_user.id)
    assert len(row["lessons"]) == 1
    cell = row["lessons"][0]
    assert cell["lesson_id"] == str(lesson.id)
    assert cell["effective_score"] is None
    assert cell["progress_id"] is None


async def test_gradebook_student_with_quiz_score(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    course, _module, lesson = await _make_quiz_course(db_session, teacher_user)
    enrollment = await make_enrollment(db_session, student_user, course)
    await make_lesson_progress(
        db_session,
        enrollment,
        lesson,
        is_completed=True,
        quiz_score=80.0,
    )

    resp = await client.get(
        f"/api/v1/courses/{course.id}/gradebook",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    cell = resp.json()["students"][0]["lessons"][0]
    assert cell["quiz_score"] == 80.0
    assert cell["effective_score"] == 80.0
    assert cell["manual_score"] is None


async def test_gradebook_manual_score_overrides_quiz(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    course, _module, lesson = await _make_quiz_course(db_session, teacher_user)
    enrollment = await make_enrollment(db_session, student_user, course)
    await make_lesson_progress(
        db_session,
        enrollment,
        lesson,
        is_completed=True,
        quiz_score=70.0,
        manual_score=95.0,
    )

    resp = await client.get(
        f"/api/v1/courses/{course.id}/gradebook",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    cell = resp.json()["students"][0]["lessons"][0]
    assert cell["effective_score"] == 95.0
    assert cell["manual_score"] == 95.0


async def test_gradebook_foreign_teacher_gets_403(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
) -> None:
    from app.models.user import User as UserModel, UserRole
    from app.services.auth_service import create_access_token, hash_password

    other = UserModel(
        email=f"other-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("pass-123"),
        full_name="Other Teacher",
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    token, _, _ = create_access_token(other)

    course = await make_course(db_session, owner=teacher_user)

    resp = await client.get(
        f"/api/v1/courses/{course.id}/gradebook",
        cookies={"access_token": token, "csrf_token": _TEST_CSRF},
    )
    assert resp.status_code == 403


async def test_gradebook_student_gets_403(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)

    resp = await client.get(
        f"/api/v1/courses/{course.id}/gradebook",
        cookies=student_token,
    )
    assert resp.status_code == 403


# ── PATCH /progress ──────────────────────────────────────────────────────────


async def test_patch_progress_sets_manual_score_and_comment(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    course, _module, lesson = await _make_quiz_course(db_session, teacher_user)
    enrollment = await make_enrollment(db_session, student_user, course)
    progress = await make_lesson_progress(
        db_session, enrollment, lesson, is_completed=True, quiz_score=50.0
    )

    resp = await client.patch(
        f"/api/v1/courses/{course.id}/progress/{progress.id}",
        json={"manual_score": 88.0, "teacher_comment": "Excellent"},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["manual_score"] == 88.0
    assert body["effective_score"] == 88.0
    assert body["teacher_comment"] == "Excellent"


async def test_patch_progress_reset_manual_score_to_null(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    """Explicit null in PATCH body clears the override, so effective_score
    falls back to quiz_score. Regression guard for exclude_unset handling.
    """
    course, _module, lesson = await _make_quiz_course(db_session, teacher_user)
    enrollment = await make_enrollment(db_session, student_user, course)
    progress = await make_lesson_progress(
        db_session,
        enrollment,
        lesson,
        is_completed=True,
        quiz_score=42.0,
        manual_score=99.0,
    )

    reset = await client.patch(
        f"/api/v1/courses/{course.id}/progress/{progress.id}",
        json={"manual_score": None},
        cookies=teacher_token,
    )
    assert reset.status_code == 200
    body = reset.json()
    assert body["manual_score"] is None
    assert body["effective_score"] == 42.0


async def test_patch_progress_partial_update(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    """Sending only teacher_comment does not reset manual_score."""
    course, _module, lesson = await _make_quiz_course(db_session, teacher_user)
    enrollment = await make_enrollment(db_session, student_user, course)
    progress = await make_lesson_progress(
        db_session,
        enrollment,
        lesson,
        is_completed=True,
        quiz_score=60.0,
        manual_score=75.0,
    )

    resp = await client.patch(
        f"/api/v1/courses/{course.id}/progress/{progress.id}",
        json={"teacher_comment": "Well done"},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["manual_score"] == 75.0
    assert body["teacher_comment"] == "Well done"


async def test_patch_progress_score_above_100_returns_422(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    course, _module, lesson = await _make_quiz_course(db_session, teacher_user)
    enrollment = await make_enrollment(db_session, student_user, course)
    progress = await make_lesson_progress(db_session, enrollment, lesson)

    resp = await client.patch(
        f"/api/v1/courses/{course.id}/progress/{progress.id}",
        json={"manual_score": 101.0},
        cookies=teacher_token,
    )
    assert resp.status_code == 422


async def test_patch_progress_score_below_0_returns_422(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    course, _module, lesson = await _make_quiz_course(db_session, teacher_user)
    enrollment = await make_enrollment(db_session, student_user, course)
    progress = await make_lesson_progress(db_session, enrollment, lesson)

    resp = await client.patch(
        f"/api/v1/courses/{course.id}/progress/{progress.id}",
        json={"manual_score": -1.0},
        cookies=teacher_token,
    )
    assert resp.status_code == 422


async def test_patch_progress_wrong_course_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    course, _module, lesson = await _make_quiz_course(db_session, teacher_user)
    other_course = await make_course(db_session, owner=teacher_user, is_published=True)
    enrollment = await make_enrollment(db_session, student_user, course)
    progress = await make_lesson_progress(db_session, enrollment, lesson)

    resp = await client.patch(
        f"/api/v1/courses/{other_course.id}/progress/{progress.id}",
        json={"manual_score": 80.0},
        cookies=teacher_token,
    )
    assert resp.status_code == 404


async def test_patch_progress_foreign_teacher_gets_403(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
) -> None:
    from app.models.user import User as UserModel, UserRole
    from app.services.auth_service import create_access_token, hash_password

    other = UserModel(
        email=f"other2-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("pass-123"),
        full_name="Other Teacher 2",
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    token, _, _ = create_access_token(other)

    course, _module, lesson = await _make_quiz_course(db_session, teacher_user)
    enrollment = await make_enrollment(db_session, student_user, course)
    progress = await make_lesson_progress(db_session, enrollment, lesson)

    resp = await client.patch(
        f"/api/v1/courses/{course.id}/progress/{progress.id}",
        json={"manual_score": 80.0},
        cookies={"access_token": token, "csrf_token": _TEST_CSRF},
    )
    assert resp.status_code == 403


async def test_patch_progress_student_gets_403(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course, _module, lesson = await _make_quiz_course(db_session, teacher_user)
    enrollment = await make_enrollment(db_session, student_user, course)
    progress = await make_lesson_progress(db_session, enrollment, lesson)

    resp = await client.patch(
        f"/api/v1/courses/{course.id}/progress/{progress.id}",
        json={"manual_score": 80.0},
        cookies=student_token,
    )
    assert resp.status_code == 403
