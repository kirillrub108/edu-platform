"""Integration tests for quiz endpoints (student fetch/submit, teacher roster, authz)."""

from __future__ import annotations

import uuid
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
    make_quiz_question,
)

pytestmark = pytest.mark.integration


async def _setup(
    db: AsyncSession, teacher: User, student: User
) -> tuple[Any, Any, Any, Any, Any]:
    """Published course → module → lesson + 2 questions + student enrollment."""
    course = await make_course(db, owner=teacher, is_published=True)
    module = await make_module(db, course)
    lesson = await make_lesson(db, module, status=LessonStatus.published)
    q1 = await make_quiz_question(db, lesson, correct_index=0, order=0)
    q2 = await make_quiz_question(db, lesson, correct_index=2, order=1)
    await make_enrollment(db, student, course)
    return course, module, lesson, q1, q2


async def _mark_complete(client: AsyncClient, lesson_id: Any, headers: dict) -> None:
    resp = await client.post(
        f"/api/v1/students/lessons/{lesson_id}/complete", headers=headers
    )
    assert resp.status_code == 200


# ── Student: fetch questions ──────────────────────────────────────────────────


async def test_fetch_quiz_returns_questions_without_correct_index(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
) -> None:
    _, _, lesson, _, _ = await _setup(db_session, teacher_user, student_user)

    resp = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/quiz", headers=student_token
    )
    assert resp.status_code == 200
    questions = resp.json()
    assert len(questions) == 2
    for q in questions:
        assert "correct_index" not in q
        assert "id" in q
        assert "question" in q
        assert "options" in q


async def test_fetch_quiz_403_if_not_enrolled(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, status=LessonStatus.published)
    await make_quiz_question(db_session, lesson)

    resp = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/quiz", headers=student_token
    )
    assert resp.status_code == 403


async def test_fetch_quiz_404_if_no_questions(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, status=LessonStatus.published)
    await make_enrollment(db_session, student_user, course)

    resp = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/quiz", headers=student_token
    )
    assert resp.status_code == 404


# ── Student: submit answers ───────────────────────────────────────────────────


async def test_submit_grades_and_persists(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
) -> None:
    _, _, lesson, q1, q2 = await _setup(db_session, teacher_user, student_user)
    await _mark_complete(client, lesson.id, student_token)

    resp = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz",
        json={
            "answers": [
                {"question_id": str(q1.id), "selected_index": 0},  # correct (idx=0)
                {"question_id": str(q2.id), "selected_index": 1},  # wrong  (idx=2)
            ]
        },
        headers=student_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 2
    assert body["correct_count"] == 1
    assert body["score"] == pytest.approx(0.5)
    assert body["passed"] is False
    assert len(body["questions"]) == 2
    for qr in body["questions"]:
        assert "correct_index" in qr

    row = await db_session.scalar(
        select(LessonProgress).where(LessonProgress.lesson_id == lesson.id)
    )
    assert row is not None
    assert row.quiz_score == pytest.approx(0.5)


async def test_submit_auto_completes_when_passing(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
) -> None:
    _, _, lesson, q1, q2 = await _setup(db_session, teacher_user, student_user)
    await _mark_complete(client, lesson.id, student_token)

    resp = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz",
        json={
            "answers": [
                {"question_id": str(q1.id), "selected_index": 0},  # correct
                {"question_id": str(q2.id), "selected_index": 2},  # correct
            ]
        },
        headers=student_token,
    )
    assert resp.status_code == 200
    assert resp.json()["passed"] is True

    row = await db_session.scalar(
        select(LessonProgress).where(LessonProgress.lesson_id == lesson.id)
    )
    assert row is not None
    assert row.is_completed is True
    assert row.quiz_score == pytest.approx(1.0)


async def test_submit_409_if_not_completed(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
) -> None:
    _, _, lesson, q1, _ = await _setup(db_session, teacher_user, student_user)

    resp = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz",
        json={"answers": [{"question_id": str(q1.id), "selected_index": 0}]},
        headers=student_token,
    )
    assert resp.status_code == 409


async def test_submit_422_unknown_question_id(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
) -> None:
    _, _, lesson, _, _ = await _setup(db_session, teacher_user, student_user)
    await _mark_complete(client, lesson.id, student_token)

    resp = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz",
        json={"answers": [{"question_id": str(uuid.uuid4()), "selected_index": 0}]},
        headers=student_token,
    )
    assert resp.status_code == 422


async def test_submit_422_duplicate_question_id(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
) -> None:
    _, _, lesson, q1, _ = await _setup(db_session, teacher_user, student_user)
    await _mark_complete(client, lesson.id, student_token)

    resp = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz",
        json={
            "answers": [
                {"question_id": str(q1.id), "selected_index": 0},
                {"question_id": str(q1.id), "selected_index": 1},
            ]
        },
        headers=student_token,
    )
    assert resp.status_code == 422


async def test_resubmit_overwrites_score(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
) -> None:
    _, _, lesson, q1, q2 = await _setup(db_session, teacher_user, student_user)
    await _mark_complete(client, lesson.id, student_token)

    await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz",
        json={
            "answers": [
                {"question_id": str(q1.id), "selected_index": 0},
                {"question_id": str(q2.id), "selected_index": 2},
            ]
        },
        headers=student_token,
    )

    resp = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz",
        json={
            "answers": [
                {"question_id": str(q1.id), "selected_index": 3},
                {"question_id": str(q2.id), "selected_index": 3},
            ]
        },
        headers=student_token,
    )
    assert resp.status_code == 200
    assert resp.json()["score"] == pytest.approx(0.0)

    row = await db_session.scalar(
        select(LessonProgress).where(LessonProgress.lesson_id == lesson.id)
    )
    assert row.quiz_score == pytest.approx(0.0)


# ── Teacher: quiz results roster ─────────────────────────────────────────────


async def test_teacher_quiz_results_roster_no_attempts(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict,
) -> None:
    _, _, lesson, _, _ = await _setup(db_session, teacher_user, student_user)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/quiz-results", headers=teacher_token
    )
    assert resp.status_code == 200
    roster = resp.json()
    assert len(roster) == 1
    row = roster[0]
    assert row["student_id"] == str(student_user.id)
    assert row["email"] == student_user.email
    assert row["quiz_score"] is None
    assert row["attempted"] is False
    assert row["completed"] is False


async def test_teacher_quiz_results_shows_score_after_attempt(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
    teacher_token: dict,
) -> None:
    _, _, lesson, q1, q2 = await _setup(db_session, teacher_user, student_user)
    await _mark_complete(client, lesson.id, student_token)
    await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz",
        json={
            "answers": [
                {"question_id": str(q1.id), "selected_index": 0},
                {"question_id": str(q2.id), "selected_index": 2},
            ]
        },
        headers=student_token,
    )

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/quiz-results", headers=teacher_token
    )
    assert resp.status_code == 200
    row = resp.json()[0]
    assert row["quiz_score"] == pytest.approx(1.0)
    assert row["attempted"] is True
    assert row["completed"] is True


# ── Authz ─────────────────────────────────────────────────────────────────────


async def test_student_cannot_access_teacher_quiz_results(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
) -> None:
    _, _, lesson, _, _ = await _setup(db_session, teacher_user, student_user)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/quiz-results", headers=student_token
    )
    assert resp.status_code == 403


async def test_teacher_cannot_submit_quiz(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict,
) -> None:
    _, _, lesson, q1, _ = await _setup(db_session, teacher_user, student_user)

    resp = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz",
        json={"answers": [{"question_id": str(q1.id), "selected_index": 0}]},
        headers=teacher_token,
    )
    assert resp.status_code == 403


async def test_non_enrolled_student_blocked_from_quiz_submit(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict,
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module, status=LessonStatus.published)
    q = await make_quiz_question(db_session, lesson)
    # No enrollment for student_user

    resp = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz",
        json={"answers": [{"question_id": str(q.id), "selected_index": 0}]},
        headers=student_token,
    )
    assert resp.status_code == 403


async def test_teacher_404_on_non_owned_lesson_quiz_results(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict,
) -> None:
    from app.models.user import User as UserModel, UserRole
    from app.services.auth_service import hash_password

    other_teacher = UserModel(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pass-123"),
        full_name="Other Teacher",
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(other_teacher)
    await db_session.commit()
    await db_session.refresh(other_teacher)

    course = await make_course(db_session, owner=other_teacher, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/quiz-results", headers=teacher_token
    )
    # get_owned_lesson returns 404 when teacher doesn't own the lesson
    assert resp.status_code == 404
