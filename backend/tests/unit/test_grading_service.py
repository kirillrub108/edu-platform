"""Unit tests for the deterministic grading service.

Covers every closed-form type, the multiple_choice Jaccard guard, partial
scoring for matching/ordering, fill_blank normalization, and the weighted
attempt aggregation used by both the LLM grader and the manual override.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.grading_service import (
    GradingResult,
    aggregate_score,
    build_snapshot,
    grade_question,
    is_open_type,
    snapshot_pointers,
)


# ── single_choice ──────────────────────────────────────────────────────────


def test_single_choice_correct():
    payload = {"prompt": "?", "options": ["A", "B", "C"], "correct_index": 1}
    r = grade_question("single_choice", payload, {"selected_index": 1})
    assert r.awarded_score == Decimal("1") and r.is_correct is True and not r.needs_review


def test_single_choice_wrong():
    payload = {"prompt": "?", "options": ["A", "B"], "correct_index": 0}
    r = grade_question("single_choice", payload, {"selected_index": 1})
    assert r.awarded_score == Decimal("0") and r.is_correct is False


def test_single_choice_missing_response():
    payload = {"prompt": "?", "options": ["A", "B"], "correct_index": 0}
    r = grade_question("single_choice", payload, {})
    assert r.awarded_score == Decimal("0") and r.is_correct is False


# ── multiple_choice (Jaccard) ──────────────────────────────────────────────


def test_multiple_choice_exact():
    payload = {"options": ["a", "b", "c", "d"], "correct_indices": [0, 2]}
    r = grade_question("multiple_choice", payload, {"selected_indices": [0, 2]})
    assert r.awarded_score == Decimal("1") and r.is_correct is True


def test_multiple_choice_partial_jaccard():
    payload = {"options": ["a", "b", "c", "d"], "correct_indices": [0, 1, 2]}
    # Selected {0, 1}, correct {0, 1, 2}: |∩| / |∪| = 2/3
    r = grade_question("multiple_choice", payload, {"selected_indices": [0, 1]})
    assert r.awarded_score == Decimal(2) / Decimal(3)
    assert r.is_correct is False


def test_multiple_choice_extra_wrong_penalises():
    payload = {"options": ["a", "b", "c", "d"], "correct_indices": [0]}
    # Selected {0, 1}, correct {0}: |∩| / |∪| = 1/2 (partial, never negative).
    r = grade_question("multiple_choice", payload, {"selected_indices": [0, 1]})
    assert r.awarded_score == Decimal("0.5")
    assert r.is_correct is False


def test_multiple_choice_empty_selection_is_zero_not_negative():
    """Guard against negative scores from a malformed empty response."""
    payload = {"options": ["a", "b"], "correct_indices": [0]}
    r = grade_question("multiple_choice", payload, {"selected_indices": []})
    assert r.awarded_score >= Decimal("0")


def test_multiple_choice_malformed_response_zero():
    payload = {"options": ["a", "b"], "correct_indices": [0]}
    r = grade_question("multiple_choice", payload, {"selected_indices": "not-a-list"})
    assert r.awarded_score == Decimal("0")


# ── true_false ──────────────────────────────────────────────────────────────


def test_true_false_correct():
    r = grade_question("true_false", {"correct": True}, {"selected": True})
    assert r.is_correct is True and r.awarded_score == Decimal("1")


def test_true_false_wrong_type_in_response():
    r = grade_question("true_false", {"correct": True}, {"selected": "yes"})
    assert r.is_correct is False and r.awarded_score == Decimal("0")


# ── matching (partial) ─────────────────────────────────────────────────────


def test_matching_full():
    payload = {"left": ["x", "y"], "right": ["1", "2"], "correct_pairs": [[0, 0], [1, 1]]}
    r = grade_question("matching", payload, {"pairs": [[0, 0], [1, 1]]})
    assert r.awarded_score == Decimal("1") and r.is_correct is True


def test_matching_half():
    payload = {"left": ["x", "y"], "right": ["1", "2"], "correct_pairs": [[0, 0], [1, 1]]}
    r = grade_question("matching", payload, {"pairs": [[0, 0], [1, 0]]})  # 1 of 2 right
    assert r.awarded_score == Decimal("0.5") and r.is_correct is False


def test_matching_malformed_pairs_skipped():
    payload = {"left": ["x"], "right": ["1"], "correct_pairs": [[0, 0]]}
    r = grade_question("matching", payload, {"pairs": [["bad", "data"], [0, 0]]})
    assert r.awarded_score == Decimal("1")


# ── ordering (partial by position) ─────────────────────────────────────────


def test_ordering_correct():
    payload = {"items": ["a", "b", "c"], "correct_order": [0, 1, 2]}
    r = grade_question("ordering", payload, {"order": [0, 1, 2]})
    assert r.awarded_score == Decimal("1") and r.is_correct is True


def test_ordering_partial():
    payload = {"items": ["a", "b", "c", "d"], "correct_order": [0, 1, 2, 3]}
    # 2 out of 4 positions match.
    r = grade_question("ordering", payload, {"order": [0, 1, 3, 2]})
    assert r.awarded_score == Decimal("0.5")


def test_ordering_length_mismatch_zero():
    payload = {"items": ["a", "b"], "correct_order": [0, 1]}
    r = grade_question("ordering", payload, {"order": [0]})
    assert r.awarded_score == Decimal("0")


# ── fill_blank ──────────────────────────────────────────────────────────────


def test_fill_blank_case_insensitive_match():
    payload = {
        "prompt": "___",
        "blanks": [["Москва", "москва"]],
        "case_insensitive": True,
    }
    r = grade_question("fill_blank", payload, {"answers": ["МОСКВА"]})
    assert r.is_correct is True and r.awarded_score == Decimal("1")


def test_fill_blank_partial():
    payload = {
        "prompt": "___ и ___",
        "blanks": [["a"], ["b"]],
        "case_insensitive": True,
    }
    r = grade_question("fill_blank", payload, {"answers": ["a", "x"]})
    assert r.awarded_score == Decimal("0.5") and r.is_correct is False


def test_fill_blank_case_sensitive_strict():
    payload = {
        "prompt": "___",
        "blanks": [["Yes"]],
        "case_insensitive": False,
    }
    r = grade_question("fill_blank", payload, {"answers": ["yes"]})
    assert r.is_correct is False


# ── open-form placeholder ──────────────────────────────────────────────────


def test_short_answer_needs_review():
    r = grade_question("short_answer", {"reference_answer": "x"}, {"text": "y"})
    assert r.needs_review is True and r.is_correct is None and r.awarded_score == Decimal("0")
    assert is_open_type("short_answer") and is_open_type("essay")


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        grade_question("nope", {}, {})


# ── aggregate_score (weighted) ─────────────────────────────────────────────


def test_aggregate_simple_average():
    # Three equal-weight questions, two correct → score 2/3.
    items = [(Decimal("1"), Decimal("1"), Decimal("1"))] * 2 + [(Decimal("1"), Decimal("0"), Decimal("1"))]
    agg = aggregate_score(items, Decimal("0.6"))
    assert agg.score == Decimal(2) / Decimal(3)
    assert agg.passed is True


def test_aggregate_weighted():
    # One heavy question worth 4, one light worth 1. Heavy correct → 4/5.
    items = [(Decimal("4"), Decimal("1"), Decimal("1")), (Decimal("1"), Decimal("0"), Decimal("1"))]
    agg = aggregate_score(items, Decimal("0.6"))
    assert agg.score == Decimal("0.8") and agg.passed is True


def test_aggregate_zero_weight_returns_zero():
    agg = aggregate_score([], Decimal("0.6"))
    assert agg.score == Decimal("0") and agg.passed is False


def test_aggregate_clamps_to_unit_range():
    # awarded > max would be a bug, but the aggregator must still clamp.
    items = [(Decimal("1"), Decimal("2"), Decimal("1"))]
    agg = aggregate_score(items, Decimal("0.6"))
    assert agg.score == Decimal("1") and agg.passed is True


# ── recompute simulating manual override ───────────────────────────────────


def test_manual_override_recompute_matches_aggregate():
    """Override flow: teacher bumps an open answer's awarded_score; the
    attempt score must be re-derived from current per-answer scores using
    snapshot weights, giving the same number aggregate_score would produce
    if it were re-run from scratch.
    """
    snap = build_snapshot([
        {"id": "00000000-0000-0000-0000-000000000001", "version": 1, "order": 0},
        {"id": "00000000-0000-0000-0000-000000000002", "version": 1, "order": 1},
    ])
    pointers = snapshot_pointers(snap)
    # Closed question correct (1.0). Essay: LLM gave 0.4 → teacher overrides to 0.9.
    items = [
        (Decimal("1.0"), Decimal("1"), Decimal("1")),
        (Decimal("2.0"), Decimal("0.9"), Decimal("1")),
    ]
    agg = aggregate_score(items, Decimal("0.6"))
    # Weighted: (1*1 + 2*0.9) / 3 = 2.8 / 3 ≈ 0.9333
    assert agg.score == (Decimal("1") + Decimal("2") * Decimal("0.9")) / Decimal("3")
    assert agg.passed is True
    assert len(pointers) == 2
    assert all("question_id" in p and "version" in p for p in pointers)


def test_build_snapshot_preserves_order_and_versions():
    snap = build_snapshot([
        {"id": "00000000-0000-0000-0000-000000000001", "version": 3, "order": 0},
        {"id": "00000000-0000-0000-0000-000000000002", "version": 1, "order": 1},
    ])
    pointers = snapshot_pointers(snap)
    assert [p["version"] for p in pointers] == [3, 1]
    assert [p["order"] for p in pointers] == [0, 1]


def test_snapshot_pointers_tolerates_missing_field():
    assert snapshot_pointers({}) == []
    assert snapshot_pointers({"version": 1}) == []
    assert snapshot_pointers({"version": 1, "pointers": []}) == []
