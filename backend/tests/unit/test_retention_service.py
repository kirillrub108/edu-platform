"""Pure retention arithmetic: the effective deletion deadline of a submission."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.constants import ATTACHMENT_RETENTION_DAYS_AFTER_GRADED, RETENTION_EXTENSION_DAYS
from app.models.assignment import AssignmentSubmission
from app.services.retention_service import effective_deadline

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)


def _submission(**kwargs: object) -> AssignmentSubmission:
    """Transient row — never added to a session, so this stays a pure test."""
    return AssignmentSubmission(**kwargs)


def test_ungraded_submission_has_no_deadline() -> None:
    assert effective_deadline(_submission(graded_at=None)) is None


def test_base_window_runs_from_graded_at() -> None:
    sub = _submission(graded_at=_NOW)
    assert effective_deadline(sub) == _NOW + timedelta(days=ATTACHMENT_RETENTION_DAYS_AFTER_GRADED)


def test_extension_overrides_the_base_window() -> None:
    extended = _NOW + timedelta(days=365)
    sub = _submission(graded_at=_NOW, attachments_retain_until=extended)
    assert effective_deadline(sub) == extended


def test_extensions_stack_from_the_current_deadline_not_from_now() -> None:
    """Two extensions must be worth twice the days — extending early never
    forfeits the time still left on the clock."""
    sub = _submission(graded_at=_NOW)
    base = effective_deadline(sub)
    assert base is not None

    sub.attachments_retain_until = base + timedelta(days=RETENTION_EXTENSION_DAYS)
    once = effective_deadline(sub)
    assert once is not None

    sub.attachments_retain_until = once + timedelta(days=RETENTION_EXTENSION_DAYS)
    twice = effective_deadline(sub)

    assert once == base + timedelta(days=RETENTION_EXTENSION_DAYS)
    assert twice == base + timedelta(days=2 * RETENTION_EXTENSION_DAYS)


def test_deadline_survives_an_ungraded_row_that_was_extended() -> None:
    """A paid extension is authoritative on its own — it does not need graded_at
    to still be set for the purge query and the API to agree."""
    extended = _NOW + timedelta(days=10)
    sub = _submission(graded_at=None, attachments_retain_until=extended)
    assert effective_deadline(sub) == extended
