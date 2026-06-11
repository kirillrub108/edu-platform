"""Pricing formulas: video estimates (both modes), ceil boundaries, partial
cancellation cost."""

from __future__ import annotations

import pytest

from app.constants import (
    AUTO_CHARS_PER_SLIDE,
    TTS_CHARS_PER_CREDIT,
    VIDEO_AUTO_BASE_CREDITS,
    VIDEO_TEXT_BASE_CREDITS,
)
from app.services.billing_service import (
    estimate_video_auto,
    estimate_video_text,
    partial_video_cost,
    partial_vision_cost,
)

pytestmark = pytest.mark.unit


# ── COST_VIDEO_TEXT = 2 + slides + ceil(chars / 3000) ────────────────────────


@pytest.mark.parametrize(
    "slides, chars, expected",
    [
        (1, 0, 2 + 1 + 0),
        (10, 2999, 2 + 10 + 1),   # just below the boundary → still 1 credit
        (10, 3000, 2 + 10 + 1),   # exact multiple → 1 credit
        (10, 3001, 2 + 10 + 2),   # one char over → rounds UP
        (10, 6000, 2 + 10 + 2),
        (40, 15000, 2 + 40 + 5),
    ],
)
def test_estimate_video_text(slides: int, chars: int, expected: int) -> None:
    assert estimate_video_text(slides, chars) == expected


def test_estimate_video_text_more_slides_costs_more() -> None:
    chars = 9000
    assert estimate_video_text(10, chars) < estimate_video_text(40, chars)


# ── COST_VIDEO_AUTO = 3 + slides + ceil(slides * 600 / 3000) ─────────────────


@pytest.mark.parametrize(
    "slides, expected",
    [
        (1, 3 + 1 + 1),    # ceil(600/3000) = 1
        (5, 3 + 5 + 1),    # ceil(3000/3000) = 1
        (6, 3 + 6 + 2),    # ceil(3600/3000) = 2
        (20, 3 + 20 + 4),  # ceil(12000/3000) = 4
    ],
)
def test_estimate_video_auto(slides: int, expected: int) -> None:
    assert estimate_video_auto(slides) == expected


def test_auto_formula_constants_match_spec() -> None:
    assert VIDEO_TEXT_BASE_CREDITS == 2
    assert VIDEO_AUTO_BASE_CREDITS == 3
    assert TTS_CHARS_PER_CREDIT == 3000
    assert AUTO_CHARS_PER_SLIDE == 600


# ── Partial cancellation: base + processed + ceil(voiced/3000) ───────────────


@pytest.mark.parametrize(
    "base, processed, voiced, expected",
    [
        (2, 0, 0, 2),           # cancel before the first slide → base only
        (2, 3, 2999, 2 + 3 + 1),
        (2, 3, 3000, 2 + 3 + 1),
        (2, 3, 3001, 2 + 3 + 2),  # partial credit of chars rounds UP
        (3, 20, 12000, 3 + 20 + 4),
    ],
)
def test_partial_video_cost(base: int, processed: int, voiced: int, expected: int) -> None:
    assert partial_video_cost(base, processed, voiced) == expected


def test_partial_never_exceeds_estimate_when_clamped() -> None:
    # Callers clamp with min(estimate, partial) — fully processed run must not
    # exceed the estimate it mirrors.
    slides, chars = 10, 9000
    estimate = estimate_video_text(slides, chars)
    full_partial = partial_video_cost(VIDEO_TEXT_BASE_CREDITS, slides, chars)
    assert min(estimate, full_partial) == estimate


# ── Vision pro-rata ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "total_cost, done, total, expected",
    [
        (5, 0, 10, 0),
        (5, 1, 10, 1),   # ceil(0.5) → rounds up per processed slide
        (5, 5, 10, 3),   # ceil(2.5)
        (5, 10, 10, 5),
        (5, 3, 0, 0),    # degenerate: no slides
    ],
)
def test_partial_vision_cost(total_cost: int, done: int, total: int, expected: int) -> None:
    assert partial_vision_cost(total_cost, done, total) == expected
