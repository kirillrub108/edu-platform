"""duration_service: per-slide word budgets and the duration they imply."""

from __future__ import annotations

import pytest

from app.constants import DETAIL_LEVEL_BODY_WORDS, WORDS_PER_MINUTE
from app.models.lesson import DetailLevel
from app.services import duration_service

pytestmark = pytest.mark.unit


def test_count_words_ignores_extra_whitespace() -> None:
    assert duration_service.count_words("  one   two\n\nthree \t four ") == 4


def test_count_words_empty() -> None:
    assert duration_service.count_words("   ") == 0


def test_estimate_duration_sec_matches_nominal_pace() -> None:
    assert duration_service.estimate_duration_sec(WORDS_PER_MINUTE) == 60
    assert duration_service.estimate_duration_sec(0) == 0


def test_body_words_per_level_is_ordered() -> None:
    brief = duration_service.body_words(DetailLevel.brief)
    auto = duration_service.body_words(DetailLevel.auto)
    high = duration_service.body_words(DetailLevel.high)
    assert brief < auto < high


def test_body_words_falls_back_to_the_default() -> None:
    """The value arrives from a DB column — an odd one must not break generation."""
    default = DETAIL_LEVEL_BODY_WORDS["auto"]
    assert duration_service.body_words(None) == default
    assert duration_service.body_words("nonsense") == default


def test_enum_member_indexes_the_table_directly() -> None:
    """DetailLevel is a str enum, so it feeds the constants dict as-is."""
    assert duration_service.body_words(DetailLevel.high) == DETAIL_LEVEL_BODY_WORDS["high"]


def test_slide_word_budgets_zero_slides_is_none() -> None:
    assert duration_service.slide_word_budgets(DetailLevel.auto, 0) is None


def test_slide_word_budgets_single_slide() -> None:
    assert duration_service.slide_word_budgets(DetailLevel.auto, 1) == [
        DETAIL_LEVEL_BODY_WORDS["auto"]
    ]


def test_slide_word_budgets_two_slides_split_evenly() -> None:
    # No body slide to contrast with, so the edge weighting is a no-op.
    budgets = duration_service.slide_word_budgets(DetailLevel.auto, 2)
    assert budgets is not None
    assert budgets[0] == budgets[1]


def test_slide_word_budgets_edges_are_smaller_than_body() -> None:
    budgets = duration_service.slide_word_budgets(DetailLevel.auto, 5)
    assert budgets is not None
    assert len(budgets) == 5
    assert budgets[0] == budgets[-1] < budgets[1]
    assert budgets[1] == budgets[2] == budgets[3]


def test_slide_word_budgets_never_drop_below_one() -> None:
    budgets = duration_service.slide_word_budgets(DetailLevel.brief, 3)
    assert budgets is not None
    assert min(budgets) >= 1


def test_deeper_detail_means_more_words_on_every_slide() -> None:
    brief = duration_service.slide_word_budgets(DetailLevel.brief, 6)
    auto = duration_service.slide_word_budgets(DetailLevel.auto, 6)
    high = duration_service.slide_word_budgets(DetailLevel.high, 6)
    assert brief is not None and auto is not None and high is not None
    assert all(b < a < h for b, a, h in zip(brief, auto, high))


def test_expected_duration_grows_with_detail_and_with_the_deck() -> None:
    brief = duration_service.expected_duration_sec(DetailLevel.brief, 10)
    auto = duration_service.expected_duration_sec(DetailLevel.auto, 10)
    high = duration_service.expected_duration_sec(DetailLevel.high, 10)
    assert brief < auto < high
    assert auto < duration_service.expected_duration_sec(DetailLevel.auto, 20)


def test_expected_duration_without_slides_is_zero() -> None:
    assert duration_service.expected_duration_sec(DetailLevel.auto, 0) == 0
    assert duration_service.expected_words(DetailLevel.auto, 0) == 0


def test_expected_duration_matches_the_budgets_handed_out() -> None:
    budgets = duration_service.slide_word_budgets(DetailLevel.high, 8)
    assert budgets is not None
    assert duration_service.expected_duration_sec(
        DetailLevel.high, 8
    ) == duration_service.estimate_duration_sec(sum(budgets))
