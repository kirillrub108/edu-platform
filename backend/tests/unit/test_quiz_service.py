"""Unit tests for quiz_service.grade_quiz."""

from __future__ import annotations

import uuid

import pytest

from app.schemas.quiz import QuizAnswerItem
from app.services.quiz_service import grade_quiz

pytestmark = pytest.mark.unit


class _MockQuestion:
    """Minimal stand-in for QuizQuestion — only the fields grade_quiz reads."""

    def __init__(self, question_id: uuid.UUID, correct_index: int) -> None:
        self.id = question_id
        self.correct_index = correct_index


def _q(correct_index: int = 0) -> _MockQuestion:
    return _MockQuestion(uuid.uuid4(), correct_index)


def _ans(q: _MockQuestion, selected_index: int) -> QuizAnswerItem:
    return QuizAnswerItem(question_id=q.id, selected_index=selected_index)


def test_all_correct() -> None:
    q1, q2 = _q(0), _q(2)
    score, correct, results = grade_quiz([q1, q2], [_ans(q1, 0), _ans(q2, 2)])
    assert score == 1.0
    assert correct == 2
    assert all(r.correct for r in results)


def test_partial_correct() -> None:
    q1, q2, q3 = _q(1), _q(0), _q(3)
    score, correct, results = grade_quiz(
        [q1, q2, q3],
        [_ans(q1, 1), _ans(q2, 1), _ans(q3, 3)],  # q2 wrong
    )
    assert score == pytest.approx(2 / 3)
    assert correct == 2
    assert results[0].correct is True
    assert results[1].correct is False
    assert results[2].correct is True


def test_all_wrong() -> None:
    q1, q2 = _q(0), _q(0)
    score, correct, _ = grade_quiz([q1, q2], [_ans(q1, 1), _ans(q2, 2)])
    assert score == 0.0
    assert correct == 0


def test_missing_answers_count_as_wrong() -> None:
    q1, q2 = _q(0), _q(1)
    score, correct, results = grade_quiz([q1, q2], [_ans(q1, 0)])
    assert score == pytest.approx(0.5)
    assert correct == 1
    assert results[0].correct is True
    assert results[1].correct is False


def test_no_answers_all_wrong() -> None:
    q1, q2 = _q(0), _q(1)
    score, correct, results = grade_quiz([q1, q2], [])
    assert score == 0.0
    assert correct == 0
    assert all(not r.correct for r in results)


def test_correct_index_exposed_in_results() -> None:
    q = _q(correct_index=2)
    _, _, results = grade_quiz([q], [_ans(q, 0)])
    assert results[0].correct_index == 2


def test_unknown_question_id_raises() -> None:
    q = _q(0)
    foreign = QuizAnswerItem(question_id=uuid.uuid4(), selected_index=0)
    with pytest.raises(ValueError, match="Unknown question_id"):
        grade_quiz([q], [foreign])


def test_duplicate_question_id_raises() -> None:
    q = _q(0)
    with pytest.raises(ValueError, match="Duplicate question_id"):
        grade_quiz([q], [_ans(q, 0), _ans(q, 1)])


def test_empty_question_list() -> None:
    score, correct, results = grade_quiz([], [])
    assert score == 0.0
    assert correct == 0
    assert results == []
