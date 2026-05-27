"""Integration tests for the student-side quiz API.

Covers the invariants stated in the design:
  * student schema never carries reference-answer fields
  * draft quizzes are 404 (no existence leak)
  * snapshot is immutable through teacher edits
  * attempts_allowed → 409 on overflow
  * passed → lesson_progress.is_completed + best-score
  * show_answers reveal only at attempts_allowed == 1
"""
from __future__ import annotations

import pytest

from app.models.quiz import QuestionType
from tests.factories import (
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
    make_quiz,
    make_quiz_question,
)


async def _setup_published_quiz(
    db_session, teacher_user, student_user,
    *, attempts_allowed: int | None = None, show_answers: bool = True,
    pass_threshold: str = "0.6",
):
    course = await make_course(db_session, teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson, published=True)
    quiz.attempts_allowed = attempts_allowed
    quiz.show_answers = show_answers
    from decimal import Decimal
    quiz.pass_threshold = Decimal(pass_threshold)
    await db_session.commit()
    q1 = await make_quiz_question(db_session, quiz, order=1, payload={
        "type": "single_choice", "prompt": "Q1",
        "options": ["A", "B", "C"], "correct_index": 1,
    })
    q2 = await make_quiz_question(
        db_session, quiz, order=2,
        type=QuestionType.true_false,
        payload={"type": "true_false", "prompt": "Q2", "correct": True},
    )
    enrollment = await make_enrollment(db_session, student_user, course)
    return course, lesson, quiz, [q1, q2], enrollment


@pytest.mark.asyncio
async def test_draft_quiz_is_404_for_student(
    client, db_session, teacher_user, student_user, student_token,
):
    course = await make_course(db_session, teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    await make_quiz(db_session, lesson)  # draft
    await make_enrollment(db_session, student_user, course)

    r = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts",
        cookies=student_token,
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_start_attempt_returns_student_schema_without_answers(
    client, db_session, teacher_user, student_user, student_token,
):
    _c, lesson, _q, _qs, _e = await _setup_published_quiz(
        db_session, teacher_user, student_user
    )
    r = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts",
        cookies=student_token,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    for q in body["questions"]:
        p = q["payload"]
        # Reference-answer fields must NEVER appear.
        assert "correct_index" not in p
        assert "correct_indices" not in p
        assert "correct" not in p
        assert "reference_answer" not in p
        assert "rubric" not in p
        assert "correct_pairs" not in p


@pytest.mark.asyncio
async def test_snapshot_invariant_under_teacher_edits(
    client, db_session, teacher_user, teacher_token, student_user, student_token,
):
    """Once the student starts an attempt, edits to the live questions do NOT
    affect the attempt's snapshot — including the correct_index used at grading.
    """
    _c, lesson, quiz, qs, _e = await _setup_published_quiz(
        db_session, teacher_user, student_user
    )
    q1 = qs[0]

    # Student starts the attempt → snapshot taken.
    r = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts",
        cookies=student_token,
    )
    assert r.status_code == 201
    attempt_id = r.json()["attempt_id"]
    snapshot_qid = r.json()["questions"][0]["id"]
    assert snapshot_qid == str(q1.id)

    # Teacher swaps correct_index on the live question.
    new_payload = {
        "type": "single_choice", "prompt": "Q1 EDITED",
        "options": ["A", "B", "C"], "correct_index": 0,
    }
    rp = await client.patch(
        f"/api/v1/lessons/{lesson.id}/quiz/questions/{q1.id}",
        cookies=teacher_token,
        json={"payload": new_payload},
    )
    assert rp.status_code == 200

    # Student submits with the ORIGINAL correct answer (index=1).
    sub = await client.put(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{attempt_id}",
        cookies=student_token,
        json={"answers": [
            {"question_id": str(q1.id), "response": {"selected_index": 1}},
            {"question_id": str(qs[1].id), "response": {"selected": True}},
        ]},
    )
    assert sub.status_code == 200
    submit = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{attempt_id}/submit",
        cookies=student_token,
    )
    assert submit.status_code == 200
    # Both answers correct against the SNAPSHOT, not the live edit.
    assert submit.json()["passed"] is True


@pytest.mark.asyncio
async def test_attempts_allowed_returns_409_after_limit(
    client, db_session, teacher_user, student_user, student_token,
):
    _c, lesson, _q, _qs, _e = await _setup_published_quiz(
        db_session, teacher_user, student_user, attempts_allowed=1,
    )
    # First start ok.
    r1 = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts",
        cookies=student_token,
    )
    assert r1.status_code == 201
    attempt_id = r1.json()["attempt_id"]
    # Submit to free the slot from "in_progress" state.
    await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{attempt_id}/submit",
        cookies=student_token,
    )
    # Second start → 409.
    r2 = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts",
        cookies=student_token,
    )
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_passed_marks_lesson_complete_and_best_score(
    client, db_session, teacher_user, student_user, student_token,
):
    _c, lesson, _q, qs, enrollment = await _setup_published_quiz(
        db_session, teacher_user, student_user
    )
    r = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts",
        cookies=student_token,
    )
    aid = r.json()["attempt_id"]
    await client.put(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}",
        cookies=student_token,
        json={"answers": [
            {"question_id": str(qs[0].id), "response": {"selected_index": 1}},
            {"question_id": str(qs[1].id), "response": {"selected": True}},
        ]},
    )
    await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}/submit",
        cookies=student_token,
    )

    from sqlalchemy import select

    from app.models.enrollment import LessonProgress
    progress = await db_session.scalar(
        select(LessonProgress).where(
            LessonProgress.enrollment_id == enrollment.id,
            LessonProgress.lesson_id == lesson.id,
        )
    )
    assert progress is not None
    assert progress.is_completed is True
    assert progress.quiz_score == 1.0


@pytest.mark.asyncio
async def test_show_answers_revealed_only_when_attempts_eq_1(
    client, db_session, teacher_user, student_user, student_token,
):
    _c, lesson, _q, qs, _e = await _setup_published_quiz(
        db_session, teacher_user, student_user,
        attempts_allowed=3, show_answers=True,
    )
    r = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts",
        cookies=student_token,
    )
    aid = r.json()["attempt_id"]
    await client.put(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}",
        cookies=student_token,
        json={"answers": [
            {"question_id": str(qs[0].id), "response": {"selected_index": 0}},
        ]},
    )
    await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}/submit",
        cookies=student_token,
    )
    result = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}",
        cookies=student_token,
    )
    assert result.status_code == 200
    body = result.json()
    for a in body["answers"]:
        assert a["correct_payload"] is None  # attempts_allowed=3 → never reveal


@pytest.mark.asyncio
async def test_show_answers_revealed_when_attempts_one(
    client, db_session, teacher_user, student_user, student_token,
):
    _c, lesson, _q, qs, _e = await _setup_published_quiz(
        db_session, teacher_user, student_user,
        attempts_allowed=1, show_answers=True,
    )
    r = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts",
        cookies=student_token,
    )
    aid = r.json()["attempt_id"]
    await client.put(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}",
        cookies=student_token,
        json={"answers": [
            {"question_id": str(qs[0].id), "response": {"selected_index": 0}},
        ]},
    )
    await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}/submit",
        cookies=student_token,
    )
    result = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}",
        cookies=student_token,
    )
    body = result.json()
    # The submitted question should carry the correct payload now.
    correct_for_q0 = next(a["correct_payload"] for a in body["answers"]
                          if a["question_id"] == str(qs[0].id))
    assert correct_for_q0 is not None
    assert correct_for_q0["correct_index"] == 1


@pytest.mark.asyncio
async def test_snapshot_pins_exact_version_after_regenerate(
    client, db_session, teacher_user, teacher_token, student_user, student_token,
):
    """Snapshot must resolve to the EXACT version pinned at attempt start,
    even after the teacher edits the question to a new version. The student's
    submit must grade against the pinned answer key.
    """
    from sqlalchemy import select

    from app.models.quiz import QuizQuestion

    _c, lesson, _quiz, qs, _e = await _setup_published_quiz(
        db_session, teacher_user, student_user
    )
    q1 = qs[0]
    # Attempt starts → pins version 1.
    r = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts",
        cookies=student_token,
    )
    assert r.status_code == 201
    aid = r.json()["attempt_id"]

    # Teacher edits → version 2 with a different correct_index.
    pe = await client.patch(
        f"/api/v1/lessons/{lesson.id}/quiz/questions/{q1.id}",
        cookies=teacher_token,
        json={"payload": {
            "type": "single_choice", "prompt": "v2",
            "options": ["A", "B", "C"], "correct_index": 2,
        }},
    )
    assert pe.status_code == 200

    versions = (await db_session.execute(
        select(QuizQuestion.version).where(QuizQuestion.id == q1.id).order_by(
            QuizQuestion.version
        )
    )).scalars().all()
    assert versions == [1, 2]

    # Student answers with index=1 (the version-1 correct answer).
    await client.put(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}",
        cookies=student_token,
        json={"answers": [
            {"question_id": str(q1.id), "response": {"selected_index": 1}},
            {"question_id": str(qs[1].id), "response": {"selected": True}},
        ]},
    )
    submit = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}/submit",
        cookies=student_token,
    )
    assert submit.status_code == 200
    # Pinned to v1 → answer is correct → passes.
    assert submit.json()["passed"] is True


@pytest.mark.asyncio
async def test_broken_snapshot_returns_500(
    client, db_session, teacher_user, student_user, student_token,
):
    """A snapshot pointing at a (id, version) row that doesn't exist must
    surface as a 500 rather than silently treating questions as missing —
    the invariant is that versions are never deleted.
    """
    from uuid import uuid4

    from app.models.quiz import AttemptStatus
    from tests.factories import make_quiz_attempt

    _c, lesson, quiz, _qs, _e = await _setup_published_quiz(
        db_session, teacher_user, student_user
    )
    bogus = {
        "version": 1,
        "pointers": [{"question_id": str(uuid4()), "version": 99, "order": 0}],
    }
    attempt = await make_quiz_attempt(
        db_session, quiz, student_user,
        questions_snapshot=bogus, attempt_number=42,
        status=AttemptStatus.in_progress,
    )
    r = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{attempt.id}",
        cookies=student_token,
    )
    assert r.status_code == 500
