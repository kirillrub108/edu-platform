"""Integration tests for the graded_by_ai flag and ai_graded computed field.

Invariants under test:
  (a) When QuizAnswer.graded_by_ai is True (task result), GET attempt result
      returns graded_by_ai=True per answer and ai_graded=True at attempt level.
  (b) An attempt composed entirely of closed questions returns ai_graded=False.
  (c) Teacher override of an AI-graded answer resets graded_by_ai=False; if no
      other AI answers remain, attempt.ai_graded becomes False.
  (d) grade_attempt is NOT in AI_GATED_ENDPOINTS (guard test stays green).
  (e) Student schema carries graded_by_ai but no reference-answer fields.

Note on SyncSession isolation: grade_attempt_task uses a psycopg2 SyncSession
that only sees committed rows. The test fixture wraps every test in a SAVEPOINT
that is rolled back, so dispatching the task via the submit endpoint leads to
"attempt not found" — the task cannot see SAVEPOINT-local data. Tests (a)–(c)
therefore set up graded_by_ai state directly via the async session and verify
the API serialisation separately. The task's flag-write logic is covered in
tests/unit/test_quiz_graded_by_ai_unit.py.
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models.quiz import AttemptStatus, QuizAnswer, QuizAttempt
from tests.factories import (
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
    make_quiz,
    make_quiz_attempt,
    make_quiz_question,
)


# ── helpers ────────────────────────────────────────────────────────────────────


async def _setup_quiz_with_open_question(db_session, teacher_user, student_user):
    """Published quiz with one short_answer question."""
    from app.models.quiz import QuestionType

    course = await make_course(db_session, teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson, published=True)
    question = await make_quiz_question(
        db_session,
        quiz,
        order=1,
        type=QuestionType.short_answer,
        payload={
            "type": "short_answer",
            "prompt": "Explain polymorphism",
            "reference_answer": "A way to use one interface for multiple types",
        },
    )
    await make_enrollment(db_session, student_user, course)
    return lesson, quiz, question


async def _setup_quiz_closed_only(db_session, teacher_user, student_user):
    """Published quiz with only closed (single_choice) questions."""
    course = await make_course(db_session, teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson, published=True)
    question = await make_quiz_question(
        db_session,
        quiz,
        order=1,
        payload={
            "type": "single_choice",
            "prompt": "Pick one",
            "options": ["A", "B"],
            "correct_index": 0,
        },
    )
    await make_enrollment(db_session, student_user, course)
    return lesson, quiz, question


async def _make_graded_attempt(
    db_session, quiz, student_user, question, *,
    graded_by_ai: bool,
):
    """Create a graded attempt with one QuizAnswer, setting graded_by_ai."""
    snapshot = {
        "version": 1,
        "pointers": [{"question_id": str(question.id), "version": question.version, "order": 1}],
    }
    attempt = await make_quiz_attempt(
        db_session,
        quiz,
        student_user,
        questions_snapshot=snapshot,
        status=AttemptStatus.graded,
        score=Decimal("0.8"),
        passed=True,
    )
    answer = QuizAnswer(
        attempt_id=attempt.id,
        question_id=question.id,
        response={"text": "Some text answer"},
        awarded_score=Decimal("0.8"),
        max_score=Decimal("1.0"),
        is_correct=False,
        needs_review=False,
        graded_by_ai=graded_by_ai,
    )
    db_session.add(answer)
    await db_session.commit()
    await db_session.refresh(answer)
    return attempt, answer


# ── (d) guard test ─────────────────────────────────────────────────────────────


def test_grade_attempt_not_in_ai_gated_endpoints():
    """grade_attempt_task is intentionally excluded from AI_GATED_ENDPOINTS
    (it's a student-facing background job, not a teacher-triggered LLM call).
    """
    from app.dependencies import AI_GATED_ENDPOINTS

    assert not any("grade" in p.lower() for _, p in AI_GATED_ENDPOINTS)


# ── (a) API serialises graded_by_ai and ai_graded ─────────────────────────────


@pytest.mark.asyncio
async def test_get_attempt_result_returns_ai_graded_true(
    client, db_session, teacher_user, student_user, student_token,
):
    """When an answer has graded_by_ai=True (set by grade_attempt_task),
    GET attempt result returns graded_by_ai=True per answer and ai_graded=True.
    """
    lesson, quiz, question = await _setup_quiz_with_open_question(
        db_session, teacher_user, student_user
    )
    attempt, _ans = await _make_graded_attempt(
        db_session, quiz, student_user, question, graded_by_ai=True
    )

    result = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{attempt.id}",
        cookies=student_token,
    )
    assert result.status_code == 200
    body = result.json()
    assert body["ai_graded"] is True
    assert body["answers"][0]["graded_by_ai"] is True


@pytest.mark.asyncio
async def test_get_attempt_result_ai_graded_false_when_flag_not_set(
    client, db_session, teacher_user, student_user, student_token,
):
    """When no answer has graded_by_ai=True, ai_graded=False."""
    lesson, quiz, question = await _setup_quiz_with_open_question(
        db_session, teacher_user, student_user
    )
    attempt, _ans = await _make_graded_attempt(
        db_session, quiz, student_user, question, graded_by_ai=False
    )

    result = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{attempt.id}",
        cookies=student_token,
    )
    assert result.status_code == 200
    body = result.json()
    assert body["ai_graded"] is False
    assert body["answers"][0]["graded_by_ai"] is False


# ── (b) closed-only attempt → ai_graded=False ─────────────────────────────────


@pytest.mark.asyncio
async def test_closed_only_attempt_ai_graded_false(
    client, db_session, teacher_user, student_user, student_token,
):
    """An attempt with only closed questions has ai_graded=False."""
    lesson, quiz, question = await _setup_quiz_closed_only(
        db_session, teacher_user, student_user
    )
    attempt, _ans = await _make_graded_attempt(
        db_session, quiz, student_user, question, graded_by_ai=False
    )

    result = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{attempt.id}",
        cookies=student_token,
    )
    assert result.status_code == 200
    body = result.json()
    assert body["ai_graded"] is False
    assert body["answers"][0]["graded_by_ai"] is False


# ── (c) override resets graded_by_ai=False ────────────────────────────────────


@pytest.mark.asyncio
async def test_override_resets_graded_by_ai(
    client, db_session, teacher_user, teacher_token, student_user, student_token,
):
    """Teacher override of an AI-graded answer sets graded_by_ai=False."""
    lesson, quiz, question = await _setup_quiz_with_open_question(
        db_session, teacher_user, student_user
    )
    attempt, answer = await _make_graded_attempt(
        db_session, quiz, student_user, question, graded_by_ai=True
    )

    # Sanity: graded_by_ai=True before override.
    assert answer.graded_by_ai is True

    override = await client.patch(
        f"/api/v1/lessons/{lesson.id}/quiz/attempts/{attempt.id}/answers/{answer.id}",
        cookies=teacher_token,
        json={"awarded_score": "0.5", "feedback": "Manual review."},
    )
    assert override.status_code == 200
    detail = override.json()

    # graded_by_ai must be reset on the answer.
    assert detail["answers"][0]["graded_by_ai"] is False
    # ai_graded on the attempt must also be False (no other AI answers).
    assert detail["ai_graded"] is False

    # DB-level confirmation.
    await db_session.refresh(answer)
    assert answer.graded_by_ai is False
    assert answer.manually_overridden is True


# ── (e) student schema carries graded_by_ai but no reference-answer fields ─────


@pytest.mark.asyncio
async def test_student_schema_has_graded_by_ai_no_reference_fields(
    client, db_session, teacher_user, student_user, student_token,
):
    """graded_by_ai is a status field — present in student schema.
    Reference-answer fields (reference_answer, correct_index, etc.) must never
    be included.
    """
    lesson, quiz, question = await _setup_quiz_with_open_question(
        db_session, teacher_user, student_user
    )
    attempt, _ans = await _make_graded_attempt(
        db_session, quiz, student_user, question, graded_by_ai=True
    )

    result = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{attempt.id}",
        cookies=student_token,
    )
    body = result.json()

    assert "graded_by_ai" in body["answers"][0]

    for ans in body["answers"]:
        assert "reference_answer" not in ans
        assert "correct_index" not in ans
        assert "correct_indices" not in ans
        assert "rubric" not in ans
