"""Unit tests: grade_attempt_task writes graded_by_ai correctly.

We test the flag-write logic by inspecting the answer objects after the task's
inner loop runs. The task is invoked via `.apply()` with a fully-mocked
SyncSession so no real DB connection is needed.

The key invariant:
  * ok=True  → ans.graded_by_ai = True
  * ok=False → ans.graded_by_ai stays False, ans.needs_review stays True
"""
from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _mock_answer(*, needs_review: bool = True) -> MagicMock:
    ans = MagicMock()
    ans.id = uuid.uuid4()
    ans.needs_review = needs_review
    ans.response = {"text": "Some text"}
    ans.awarded_score = None
    ans.max_score = Decimal("1.0")
    ans.is_correct = None
    ans.llm_feedback = None
    ans.graded_by_ai = False
    return ans


def _mock_question(qid: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=qid,
        version=1,
        type="short_answer",
        payload={"type": "short_answer", "prompt": "Q", "reference_answer": "A"},
        weight=Decimal("1.0"),
    )


def _run_task_with_patched_db(monkeypatch, answer, snap_q, ok: bool):
    """Helper: run grade_attempt_task.apply() with a fully-mocked SyncSession."""
    from app.tasks.quiz_pipeline import grade_attempt_task

    attempt_id = uuid.uuid4()
    quiz_id = uuid.uuid4()
    answer.question_id = snap_q.id

    mock_attempt = MagicMock()
    mock_attempt.id = attempt_id
    mock_attempt.quiz_id = quiz_id
    mock_attempt.answers = [answer]
    mock_attempt.questions_snapshot = {"version": 1, "pointers": []}
    mock_attempt.score = None
    mock_attempt.passed = None
    mock_attempt.status = "submitted"
    mock_attempt.graded_at = None
    mock_attempt.grading_task_id = None

    mock_quiz = MagicMock()
    mock_quiz.pass_threshold = Decimal("0.6")

    mock_session = MagicMock()
    _db_map = {attempt_id: mock_attempt, quiz_id: mock_quiz, answer.id: answer}
    mock_session.get.side_effect = lambda model, pk: _db_map.get(pk)

    monkeypatch.setattr(
        "app.tasks.quiz_pipeline.resolve_snapshot_sync",
        lambda session, snapshot: [snap_q],
    )
    monkeypatch.setattr(
        "app.tasks.quiz_pipeline.resolved_index",
        lambda resolved: {snap_q.id: snap_q},
    )
    monkeypatch.setattr(
        "app.tasks.quiz_pipeline.is_open_type",
        lambda qtype: True,
    )
    monkeypatch.setattr(
        "app.tasks.quiz_pipeline.aggregate_score",
        lambda items, threshold: SimpleNamespace(score=Decimal("0.9"), passed=True),
    )
    monkeypatch.setattr(
        "app.tasks.quiz_pipeline._mark_lesson_progress_if_passed",
        lambda session, attempt: None,
    )
    monkeypatch.setattr(
        "app.tasks.quiz_pipeline._grade_one_open",
        lambda ans_id, payload, text, quiz_id=None: (ans_id, 0.9, "Good.", ok),
    )

    session_ctx = MagicMock()
    session_ctx.__enter__ = MagicMock(return_value=mock_session)
    session_ctx.__exit__ = MagicMock(return_value=False)

    with patch("app.tasks.quiz_pipeline.SyncSession", return_value=session_ctx):
        # apply() creates a proper EAGER request context (self.request.id is set).
        grade_attempt_task.apply(args=[str(attempt_id)])

    return answer


def test_grade_attempt_sets_graded_by_ai_true_on_successful_llm(monkeypatch):
    """When _grade_one_open returns ok=True, graded_by_ai must be set to True."""
    answer = _mock_answer(needs_review=True)
    snap_q = _mock_question(uuid.uuid4())
    result_answer = _run_task_with_patched_db(monkeypatch, answer, snap_q, ok=True)
    assert result_answer.graded_by_ai is True
    assert result_answer.needs_review is False


def test_grade_attempt_does_not_set_graded_by_ai_on_llm_failure(monkeypatch):
    """When _grade_one_open returns ok=False, graded_by_ai must stay False."""
    answer = _mock_answer(needs_review=True)
    snap_q = _mock_question(uuid.uuid4())
    result_answer = _run_task_with_patched_db(monkeypatch, answer, snap_q, ok=False)
    assert result_answer.graded_by_ai is False
    # needs_review stays True — teacher must review it.
    assert result_answer.needs_review is True
