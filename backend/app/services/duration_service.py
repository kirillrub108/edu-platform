"""Narration volume arithmetic: per-slide word budgets and duration estimates.

Pure functions — no DB, no I/O — so both the async routers and the sync Celery
tasks can share them.

The teacher picks how deeply the narration covers each slide; the lesson's
length follows from that choice and the size of the deck. Duration is never an
input, and TTS speed is never touched — see docs/DECISIONS.md.
"""

from app.constants import (
    DEFAULT_DETAIL_LEVEL,
    DETAIL_LEVEL_BODY_WORDS,
    EDGE_SLIDE_BUDGET_WEIGHT,
    WORDS_PER_MINUTE,
)


def count_words(text: str) -> int:
    """Whitespace-separated word count — the same unit the prompts speak in."""
    return len(text.split())


def estimate_duration_sec(word_count: int) -> int:
    """Spoken duration of *word_count* words at the nominal pace."""
    return round(word_count / WORDS_PER_MINUTE * 60)


def body_words(detail_level: str | None) -> int:
    """Word budget for one body slide at this level of detail.

    An unknown or missing level falls back to the default rather than raising:
    the value reaches here from a DB column, and a lesson must stay generatable
    even if that column ever holds something unexpected.
    """
    return DETAIL_LEVEL_BODY_WORDS.get(
        detail_level or DEFAULT_DETAIL_LEVEL, DETAIL_LEVEL_BODY_WORDS[DEFAULT_DETAIL_LEVEL]
    )


def _slide_weights(slide_count: int) -> list[float]:
    """Relative share of the word budget per slide.

    Body slides weigh 1.0; the first and last (title / closing) carry far less
    content, so they weigh EDGE_SLIDE_BUDGET_WEIGHT. With two slides or fewer
    there is no body slide to contrast with, so the weighting is a no-op.
    """
    weights = [1.0] * slide_count
    if slide_count > 2:
        weights[0] = EDGE_SLIDE_BUDGET_WEIGHT
        weights[-1] = EDGE_SLIDE_BUDGET_WEIGHT
    return weights


def slide_word_budgets(detail_level: str | None, slide_count: int) -> list[int] | None:
    """Per-slide word budgets, or None when there are no slides to spread over."""
    if slide_count <= 0:
        return None
    per_body = body_words(detail_level)
    return [max(1, round(per_body * w)) for w in _slide_weights(slide_count)]


def expected_words(detail_level: str | None, slide_count: int) -> int:
    """Total narration volume this deck is expected to produce, in words."""
    budgets = slide_word_budgets(detail_level, slide_count)
    return sum(budgets) if budgets else 0


def expected_duration_sec(detail_level: str | None, slide_count: int) -> int:
    """Approximate lesson length for this deck at this level of detail.

    This is what the teacher is shown next to the choice — the number moves
    with the detail level and with how many slides the presentation has.
    """
    return estimate_duration_sec(expected_words(detail_level, slide_count))
