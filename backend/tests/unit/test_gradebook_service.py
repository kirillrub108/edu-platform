"""Unit tests for gradebook_service.compute_effective_score."""

from __future__ import annotations

import pytest

from app.services.gradebook_service import compute_effective_score


@pytest.mark.parametrize(
    ("quiz_score", "manual_score", "expected"),
    [
        (None, None, None),
        (75.0, None, 75.0),
        (75.0, 90.0, 90.0),
        (None, 60.0, 60.0),
        # manual_score=0 is a valid override, not falsy-None
        (80.0, 0.0, 0.0),
    ],
)
def test_compute_effective_score(
    quiz_score: float | None,
    manual_score: float | None,
    expected: float | None,
) -> None:
    assert compute_effective_score(quiz_score, manual_score) == expected
