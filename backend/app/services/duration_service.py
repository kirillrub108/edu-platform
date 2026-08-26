"""Lesson-duration arithmetic: word budgets and duration estimates.

Pure functions — no DB, no I/O — so both the async routers and the sync Celery
tasks can share them. The teacher's target duration is realised as a word
budget handed to the narration prompt; TTS speed is never touched (see
docs/DECISIONS.md).
"""

from app.constants import (
    DURATION_MISMATCH_RATIO,
    EDGE_SLIDE_BUDGET_WEIGHT,
    WORDS_PER_MINUTE,
)


def count_words(text: str) -> int:
    """Whitespace-separated word count — the same unit the prompts speak in."""
    return len(text.split())


def estimate_duration_sec(word_count: int) -> int:
    """Spoken duration of *word_count* words at the nominal pace."""
    return round(word_count / WORDS_PER_MINUTE * 60)


def slide_word_budgets(target_duration_min: int | None, slide_count: int) -> list[int] | None:
    """Per-slide word budgets, or None when there is no target to spread.

    The first and last slides (title / closing) carry less content than body
    slides, so they get EDGE_SLIDE_BUDGET_WEIGHT of a body slide's share. The
    weights are normalised, so the budgets always add up to the target.

    None means "no explicit volume constraint" and leaves the prompt as it was
    before target durations existed.
    """
    if target_duration_min is None or slide_count <= 0:
        return None

    weights = [1.0] * slide_count
    if slide_count > 2:
        weights[0] = EDGE_SLIDE_BUDGET_WEIGHT
        weights[-1] = EDGE_SLIDE_BUDGET_WEIGHT

    total_words = target_duration_min * WORDS_PER_MINUTE
    weight_sum = sum(weights)
    return [max(1, round(total_words * w / weight_sum)) for w in weights]


def mismatch_warning(target_duration_min: int | None, text: str) -> str | None:
    """Warn when authored text is off the target by more than the threshold.

    Advisory only: the caller must not block generation on it.
    """
    if target_duration_min is None:
        return None
    estimated = estimate_duration_sec(count_words(text))
    target_sec = target_duration_min * 60
    if abs(estimated - target_sec) <= target_sec * DURATION_MISMATCH_RATIO:
        return None
    verb = "короче" if estimated < target_sec else "длиннее"
    return (
        f"Текст лекции примерно на {round(estimated / 60)} мин — это заметно {verb} "
        f"целевых {target_duration_min} мин. Авторский текст не сокращается и не "
        f"дополняется автоматически."
    )
