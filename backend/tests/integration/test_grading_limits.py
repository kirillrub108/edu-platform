"""Anti-abuse limits on the FREE open-answer LLM grading (students only).

  * open answer over the char cap → 422 answer_too_long (before any LLM call)
  * 6th graded submission per quiz per day → 429 grading_rate_limited
  * a purely-closed submission never consumes the daily grading slot
  * the slot is per-day: a fresh period_key resets the cap

Teacher balances/quotas are untouched here — the cap rides usage_counters,
the same atomic UPSERT the lifetime trial uses.
"""
from __future__ import annotations

from typing import Any

import pytest

from app.constants import (
    GRADING_MAX_ANSWER_CHARS,
    GRADING_MAX_ATTEMPTS_PER_QUIZ_PER_DAY,
)
from app.models.quiz import QuestionType
from app.services import quota_service
from tests.factories import (
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
    make_quiz,
    make_quiz_question,
)

pytestmark = pytest.mark.integration


class _FakeTask:
    id = "grade-task-stub"


@pytest.fixture()
def stub_grade_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop the eager grade_attempt_task from hitting a real LLM. The router
    still reserves the daily slot before enqueuing — that's what we assert."""
    from app.routers import quiz_student as qs_router

    monkeypatch.setattr(
        qs_router.grade_attempt_task, "apply_async", lambda *a, **k: _FakeTask()
    )


async def _setup_open_quiz(db_session: Any, teacher_user: Any, student_user: Any):
    """Published quiz with a single short_answer (open) question + enrollment."""
    course = await make_course(db_session, teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson, published=True)
    q = await make_quiz_question(
        db_session, quiz, order=1,
        type=QuestionType.short_answer,
        payload={
            "type": "short_answer",
            "prompt": "Explain photosynthesis.",
            "reference_answer": "Plants convert light to energy.",
            "rubric": "",
        },
    )
    await make_enrollment(db_session, student_user, course)
    return lesson, quiz, q


async def _submit_open_answer(
    client: Any, lesson_id: Any, qid: Any, token: dict[str, str], text: str
):
    """Run one full start → save → submit cycle with an open answer."""
    start = await client.post(
        f"/api/v1/students/lessons/{lesson_id}/quiz/attempts", cookies=token
    )
    assert start.status_code == 201, start.text
    aid = start.json()["attempt_id"]
    save = await client.put(
        f"/api/v1/students/lessons/{lesson_id}/quiz/attempts/{aid}",
        cookies=token,
        json={"answers": [{"question_id": str(qid), "response": {"text": text}}]},
    )
    assert save.status_code == 200, save.text
    return await client.post(
        f"/api/v1/students/lessons/{lesson_id}/quiz/attempts/{aid}/submit",
        cookies=token,
    )


@pytest.mark.asyncio
async def test_overlong_open_answer_returns_422(
    client, db_session, teacher_user, student_user, student_token, stub_grade_task,
):
    lesson, _quiz, q = await _setup_open_quiz(db_session, teacher_user, student_user)
    over = "x" * (GRADING_MAX_ANSWER_CHARS + 1)
    resp = await _submit_open_answer(client, lesson.id, q.id, student_token, over)
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["code"] == "answer_too_long"
    assert detail["limit"] == GRADING_MAX_ANSWER_CHARS
    assert detail["length"] == GRADING_MAX_ANSWER_CHARS + 1


@pytest.mark.asyncio
async def test_sixth_submission_per_day_returns_429(
    client, db_session, teacher_user, student_user, student_token, stub_grade_task,
):
    lesson, _quiz, q = await _setup_open_quiz(db_session, teacher_user, student_user)

    for i in range(GRADING_MAX_ATTEMPTS_PER_QUIZ_PER_DAY):
        ok = await _submit_open_answer(
            client, lesson.id, q.id, student_token, f"answer {i}"
        )
        assert ok.status_code == 200, f"submission {i + 1}: {ok.text}"

    sixth = await _submit_open_answer(
        client, lesson.id, q.id, student_token, "one too many"
    )
    assert sixth.status_code == 429
    detail = sixth.json()["detail"]
    assert detail["code"] == "grading_rate_limited"
    assert detail["limit"] == GRADING_MAX_ATTEMPTS_PER_QUIZ_PER_DAY
    assert detail["used"] == GRADING_MAX_ATTEMPTS_PER_QUIZ_PER_DAY


@pytest.mark.asyncio
async def test_closed_only_submission_does_not_consume_slot(
    client, db_session, teacher_user, student_user, student_token,
):
    """A quiz with no open questions grades synchronously and never touches the
    daily grading counter."""
    course = await make_course(db_session, teacher_user, is_published=True)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)
    quiz = await make_quiz(db_session, lesson, published=True)
    q = await make_quiz_question(
        db_session, quiz, order=1,
        payload={
            "type": "single_choice", "prompt": "Q1",
            "options": ["A", "B"], "correct_index": 0,
        },
    )
    await make_enrollment(db_session, student_user, course)

    start = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts", cookies=student_token
    )
    aid = start.json()["attempt_id"]
    await client.put(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}",
        cookies=student_token,
        json={"answers": [{"question_id": str(q.id), "response": {"selected_index": 0}}]},
    )
    submit = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/quiz/attempts/{aid}/submit",
        cookies=student_token,
    )
    assert submit.status_code == 200

    used = await quota_service.get_usage(
        db_session,
        student_user.id,
        quota_service.grading_resource(quiz.id),
        quota_service.utc_day_key(),
    )
    assert used == 0


@pytest.mark.asyncio
async def test_next_day_resets_the_cap(
    client, db_session, teacher_user, student_user, student_token,
    stub_grade_task, monkeypatch,
):
    lesson, _quiz, q = await _setup_open_quiz(db_session, teacher_user, student_user)

    # Pin "today" so the cap fills against a known period_key.
    monkeypatch.setattr(quota_service, "utc_day_key", lambda now=None: "2026-01-01")
    for i in range(GRADING_MAX_ATTEMPTS_PER_QUIZ_PER_DAY):
        ok = await _submit_open_answer(client, lesson.id, q.id, student_token, f"a{i}")
        assert ok.status_code == 200
    blocked = await _submit_open_answer(client, lesson.id, q.id, student_token, "x")
    assert blocked.status_code == 429

    # Roll the clock to the next day → new period_key → fresh budget.
    monkeypatch.setattr(quota_service, "utc_day_key", lambda now=None: "2026-01-02")
    fresh = await _submit_open_answer(client, lesson.id, q.id, student_token, "new day")
    assert fresh.status_code == 200
