"""Unit tests for the per-type quiz generation request.

The dialog sends one count per question type (0 = type excluded); these tests
pin the bounds the UI mirrors and the resolved mapping the router hands to the
Celery task — including the total that the credit reservation is sized against.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.constants import (
    QUIZ_DEFAULT_TYPE_COUNTS,
    QUIZ_MAX_QUESTIONS,
    QUIZ_MAX_QUESTIONS_PER_TYPE,
    QUIZ_MIN_QUESTIONS,
)
from app.schemas.quiz import QuizGenerateRequest

pytestmark = pytest.mark.unit


def _req(**counts: int) -> QuizGenerateRequest:
    return QuizGenerateRequest(
        type_counts=[{"type": t, "count": c} for t, c in counts.items()]  # type: ignore[list-item]
    )


def test_omitted_counts_fall_back_to_the_defaults() -> None:
    resolved = QuizGenerateRequest().resolved_type_counts()

    assert resolved == {t: c for t, c in QUIZ_DEFAULT_TYPE_COUNTS.items() if c > 0}
    assert all(c > 0 for c in resolved.values())


def test_zero_count_types_are_dropped_not_generated() -> None:
    resolved = _req(single_choice=2, true_false=0).resolved_type_counts()

    assert resolved == {"single_choice": 2}


def test_resolved_total_is_the_sum_of_the_per_type_counts() -> None:
    """The credit reservation is sized off this total — no redistribution."""
    resolved = _req(single_choice=2, multiple_choice=3, short_answer=1).resolved_type_counts()

    assert sum(resolved.values()) == 6


def test_all_zero_is_rejected() -> None:
    with pytest.raises(ValidationError, match=f"at least {QUIZ_MIN_QUESTIONS}"):
        _req(single_choice=0, true_false=0)


def test_negative_count_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _req(single_choice=-1)


def test_fractional_count_is_rejected() -> None:
    with pytest.raises(ValidationError):
        QuizGenerateRequest(
            type_counts=[{"type": "single_choice", "count": 1.5}]  # type: ignore[list-item]
        )


def test_per_type_ceiling_is_enforced() -> None:
    with pytest.raises(ValidationError):
        _req(single_choice=QUIZ_MAX_QUESTIONS_PER_TYPE + 1)


def test_total_ceiling_is_enforced_across_types() -> None:
    """Each type stays under its own cap while the sum blows the total cap."""
    per_type = QUIZ_MAX_QUESTIONS_PER_TYPE
    types = ["single_choice", "multiple_choice", "true_false"]
    assert per_type * len(types) > QUIZ_MAX_QUESTIONS

    with pytest.raises(ValidationError, match=f"exceed {QUIZ_MAX_QUESTIONS}"):
        QuizGenerateRequest(
            type_counts=[{"type": t, "count": per_type} for t in types]  # type: ignore[list-item]
        )


def test_duplicate_type_is_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate question type"):
        QuizGenerateRequest(
            type_counts=[  # type: ignore[list-item]
                {"type": "single_choice", "count": 1},
                {"type": "single_choice", "count": 2},
            ]
        )


def test_non_generatable_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        QuizGenerateRequest(
            type_counts=[{"type": "essay", "count": 1}]  # type: ignore[list-item]
        )
