"""duration_service: word budgets and spoken-duration estimates."""

from __future__ import annotations

import pytest

from app.constants import DURATION_MISMATCH_RATIO, WORDS_PER_MINUTE
from app.services import duration_service

pytestmark = pytest.mark.unit


def test_count_words_ignores_extra_whitespace() -> None:
    assert duration_service.count_words("  one   two\n\nthree \t four ") == 4


def test_count_words_empty() -> None:
    assert duration_service.count_words("   ") == 0


def test_estimate_duration_sec_matches_nominal_pace() -> None:
    assert duration_service.estimate_duration_sec(WORDS_PER_MINUTE) == 60
    assert duration_service.estimate_duration_sec(0) == 0


def test_slide_word_budgets_none_target_keeps_current_behaviour() -> None:
    assert duration_service.slide_word_budgets(None, 10) is None


def test_slide_word_budgets_single_slide_gets_whole_budget() -> None:
    assert duration_service.slide_word_budgets(10, 1) == [10 * WORDS_PER_MINUTE]


def test_slide_word_budgets_two_slides_split_evenly() -> None:
    # No body slide to contrast with, so the edge weighting is a no-op.
    budgets = duration_service.slide_word_budgets(10, 2)
    assert budgets is not None
    assert budgets[0] == budgets[1]


def test_slide_word_budgets_edges_are_smaller_than_body() -> None:
    budgets = duration_service.slide_word_budgets(15, 5)
    assert budgets is not None
    assert len(budgets) == 5
    assert budgets[0] == budgets[-1] < budgets[1]
    assert budgets[1] == budgets[2] == budgets[3]


def test_slide_word_budgets_sum_to_the_target() -> None:
    target_words = 20 * WORDS_PER_MINUTE
    budgets = duration_service.slide_word_budgets(20, 7)
    assert budgets is not None
    # Rounding per slide, so allow a slide's worth of slack.
    assert abs(sum(budgets) - target_words) <= len(budgets)


def test_slide_word_budgets_many_slides_never_drop_below_one() -> None:
    budgets = duration_service.slide_word_budgets(5, 5000)
    assert budgets is not None
    assert min(budgets) == 1


def test_slide_word_budgets_zero_slides_is_none() -> None:
    assert duration_service.slide_word_budgets(15, 0) is None


def test_mismatch_warning_none_target_never_warns() -> None:
    assert duration_service.mismatch_warning(None, "word " * 5000) is None


def test_mismatch_warning_within_threshold_is_silent() -> None:
    # Exactly on target, and at the edge of the allowed band.
    on_target = "word " * (10 * WORDS_PER_MINUTE)
    assert duration_service.mismatch_warning(10, on_target) is None

    edge_words = round(10 * WORDS_PER_MINUTE * (1 + DURATION_MISMATCH_RATIO))
    assert duration_service.mismatch_warning(10, "word " * edge_words) is None


def test_mismatch_warning_flags_short_text() -> None:
    warning = duration_service.mismatch_warning(30, "word " * 100)
    assert warning is not None
    assert "30" in warning


def test_mismatch_warning_flags_long_text() -> None:
    warning = duration_service.mismatch_warning(5, "word " * (30 * WORDS_PER_MINUTE))
    assert warning is not None


def test_mismatch_warning_empty_text_against_target() -> None:
    assert duration_service.mismatch_warning(5, "") is not None
