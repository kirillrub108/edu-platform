"""Open-answer length cap (anti-abuse) — boundary at GRADING_MAX_ANSWER_CHARS."""
from __future__ import annotations

from app.constants import GRADING_MAX_ANSWER_CHARS
from app.services.grading_service import open_answer_too_long


def test_answer_exactly_at_cap_is_allowed() -> None:
    assert open_answer_too_long("x" * GRADING_MAX_ANSWER_CHARS) is False


def test_answer_one_over_cap_is_rejected() -> None:
    assert open_answer_too_long("x" * (GRADING_MAX_ANSWER_CHARS + 1)) is True
