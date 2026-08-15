"""Unit tests for the polymorphic quiz payload schemas (app.schemas.quiz).

Two things are pinned here:

  * the per-type `model_validator`s, which are the last gate before a broken
    question (index out of range, non-permutation ordering) is stored and
    handed to students;
  * `to_student_payload`, which strips every reference-answer field — a leak
    there hands out the answer key.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from app.schemas.quiz import (
    FillBlankPayloadT,
    MatchingPayloadT,
    MultipleChoicePayloadT,
    OrderingPayloadT,
    QuizSettingsUpdate,
    SingleChoicePayloadT,
    to_student_payload,
)

pytestmark = pytest.mark.unit

_TEACHER_PAYLOADS: dict[str, dict[str, Any]] = {
    "single_choice": {
        "type": "single_choice",
        "prompt": "Что это?",
        "options": ["a", "b"],
        "correct_index": 1,
        "explanation": "потому что",
    },
    "multiple_choice": {
        "type": "multiple_choice",
        "prompt": "Что верно?",
        "options": ["a", "b", "c"],
        "correct_indices": [0, 2],
        "explanation": "потому что",
    },
    "true_false": {
        "type": "true_false",
        "prompt": "Утверждение",
        "correct": True,
        "explanation": "потому что",
    },
    "short_answer": {
        "type": "short_answer",
        "prompt": "Назовите",
        "reference_answer": "энтропия",
        "rubric": "по сути",
    },
    "essay": {"type": "essay", "prompt": "Опишите", "rubric": "полнота, точность"},
    "matching": {
        "type": "matching",
        "prompt": "Сопоставьте",
        "left": ["l1", "l2"],
        "right": ["r1", "r2"],
        "correct_pairs": [[0, 1], [1, 0]],
        "explanation": "потому что",
    },
    "ordering": {
        "type": "ordering",
        "prompt": "Упорядочьте",
        "items": ["i1", "i2", "i3"],
        "correct_order": [2, 0, 1],
        "explanation": "потому что",
    },
    "fill_blank": {
        "type": "fill_blank",
        "prompt": "Вода кипит при ___ градусах",
        "blanks": [["100", "ста"]],
        "case_insensitive": True,
        "explanation": "потому что",
    },
}

# Every key that would give the answer away if it reached a student.
_SECRET_KEYS = {
    "correct_index",
    "correct_indices",
    "correct",
    "correct_pairs",
    "correct_order",
    "reference_answer",
    "rubric",
    "blanks",
    "explanation",
}


# ── payload validators ────────────────────────────────────────────────────────


def test_single_choice_rejects_index_past_the_last_option() -> None:
    with pytest.raises(ValidationError, match="correct_index out of range"):
        SingleChoicePayloadT(prompt="Q", options=["a", "b"], correct_index=2)


def test_multiple_choice_rejects_duplicate_indices() -> None:
    with pytest.raises(ValidationError, match="must be unique"):
        MultipleChoicePayloadT(prompt="Q", options=["a", "b"], correct_indices=[1, 1])


def test_multiple_choice_rejects_out_of_range_index() -> None:
    with pytest.raises(ValidationError, match="correct_indices out of range"):
        MultipleChoicePayloadT(prompt="Q", options=["a", "b"], correct_indices=[0, 5])


def test_matching_rejects_left_index_out_of_range() -> None:
    with pytest.raises(ValidationError, match="left index out of range"):
        MatchingPayloadT(prompt="Q", left=["l1", "l2"], right=["r1", "r2"], correct_pairs=[(2, 0)])


def test_matching_rejects_right_index_out_of_range() -> None:
    with pytest.raises(ValidationError, match="right index out of range"):
        MatchingPayloadT(prompt="Q", left=["l1", "l2"], right=["r1", "r2"], correct_pairs=[(0, 9)])


def test_matching_rejects_duplicate_left_indices() -> None:
    """One left item may not map to two right items — the grader assumes 1:1."""
    with pytest.raises(ValidationError, match="duplicate left indices"):
        MatchingPayloadT(
            prompt="Q", left=["l1", "l2"], right=["r1", "r2"], correct_pairs=[(0, 0), (0, 1)]
        )


def test_matching_accepts_a_full_bijection() -> None:
    payload = MatchingPayloadT(
        prompt="Q", left=["l1", "l2"], right=["r1", "r2"], correct_pairs=[(0, 1), (1, 0)]
    )
    assert payload.correct_pairs == [(0, 1), (1, 0)]


@pytest.mark.parametrize("order", [[0, 1], [0, 1, 1], [1, 2, 3]])
def test_ordering_requires_a_permutation_of_all_items(order: list[int]) -> None:
    with pytest.raises(ValidationError, match="permutation"):
        OrderingPayloadT(prompt="Q", items=["a", "b", "c"], correct_order=order)


def test_ordering_accepts_a_full_permutation() -> None:
    payload = OrderingPayloadT(prompt="Q", items=["a", "b", "c"], correct_order=[2, 0, 1])
    assert payload.correct_order == [2, 0, 1]


@pytest.mark.parametrize("blanks", [[[]], [["", "  "]], [["100"], ["ста"]]])
def test_fill_blank_rejects_broken_blank_sets(blanks: list[list[str]]) -> None:
    """Empty alternatives, or a blank count that disagrees with the '___'
    markers in the prompt."""
    with pytest.raises(ValidationError):
        FillBlankPayloadT(prompt="Вода кипит при ___ градусах", blanks=blanks)


def test_fill_blank_accepts_one_marker_per_blank() -> None:
    payload = FillBlankPayloadT(
        prompt="___ плюс ___ равно двум", blanks=[["один", "1"], ["один", "1"]]
    )
    assert payload.case_insensitive is True


# ── QuizSettingsUpdate ────────────────────────────────────────────────────────


def test_attempts_allowed_below_one_is_rejected() -> None:
    with pytest.raises(ValidationError, match="attempts_allowed must be >= 1 or null"):
        QuizSettingsUpdate(attempts_allowed=0)


def test_attempts_allowed_null_means_unlimited() -> None:
    assert QuizSettingsUpdate(attempts_allowed=None).attempts_allowed is None


def test_attempts_allowed_omitted_stays_unset() -> None:
    """The sentinel distinguishes "not sent" from an explicit null."""
    assert QuizSettingsUpdate().attempts_allowed == "__unset__"


# ── to_student_payload ────────────────────────────────────────────────────────


@pytest.mark.parametrize("qtype", sorted(_TEACHER_PAYLOADS))
def test_student_payload_never_leaks_answer_fields(qtype: str) -> None:
    student = to_student_payload(_TEACHER_PAYLOADS[qtype])

    assert student["type"] == qtype
    assert student["prompt"] == _TEACHER_PAYLOADS[qtype]["prompt"]
    assert _SECRET_KEYS.isdisjoint(student)


def test_student_payload_keeps_the_choices_needed_to_answer() -> None:
    assert to_student_payload(_TEACHER_PAYLOADS["single_choice"])["options"] == ["a", "b"]
    assert to_student_payload(_TEACHER_PAYLOADS["multiple_choice"])["options"] == ["a", "b", "c"]
    matching = to_student_payload(_TEACHER_PAYLOADS["matching"])
    assert (matching["left"], matching["right"]) == (["l1", "l2"], ["r1", "r2"])
    assert to_student_payload(_TEACHER_PAYLOADS["ordering"])["items"] == ["i1", "i2", "i3"]


def test_student_payload_reports_blank_count_not_the_answers() -> None:
    student = to_student_payload(_TEACHER_PAYLOADS["fill_blank"])
    assert student["blanks_count"] == 1


def test_student_payload_rejects_an_unknown_type() -> None:
    with pytest.raises(ValueError, match="unknown question type"):
        to_student_payload({"type": "telepathy", "prompt": "Угадайте"})
