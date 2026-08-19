"""Retention of assignment-submission attachments: effective deadline, paid
extension and the pre-deletion reminder.

The effective deadline of one submission is

    attachments_retain_until  OR  graded_at + ATTACHMENT_RETENTION_DAYS_AFTER_GRADED

i.e. the free base window unless a paid extension moved it. Extensions
accumulate: each one adds RETENTION_EXTENSION_DAYS to the CURRENT effective
deadline rather than to `now`, so extending early never silently costs the
teacher the days they had left.

Async functions serve the teacher endpoint (AsyncSession); the `sync_*` helpers
serve purge_pipeline and the reminder task on their psycopg2 Session — never
import the async ones into `app/tasks/*`.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import structlog
from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    ATTACHMENT_RETENTION_DAYS_AFTER_GRADED,
    RETENTION_EXTENSION_DAYS,
    RETENTION_REMINDER_DAYS_BEFORE,
)
from app.models.assignment import AssignmentAttachment, AssignmentSubmission
from app.models.credit import CreditOperation
from app.services import billing_service

logger = structlog.get_logger()

_BASE_WINDOW = timedelta(days=ATTACHMENT_RETENTION_DAYS_AFTER_GRADED)


def _isoformat(moment: datetime | None) -> str | None:
    return moment.isoformat() if moment is not None else None


# ── Effective deadline (pure) ────────────────────────────────────────────────


def effective_deadline(submission: AssignmentSubmission) -> datetime | None:
    """When this submission's attachments become purgeable. None while ungraded
    (the retention clock only starts at grading)."""
    if submission.attachments_retain_until is not None:
        return submission.attachments_retain_until
    if submission.graded_at is None:
        return None
    return submission.graded_at + _BASE_WINDOW


def extension_price(submission: AssignmentSubmission) -> int:
    """Price of one extension for an already-loaded submission.

    Reads `submission.attachments` from memory (the teacher serializers eager-load
    it), so rendering a price costs no extra query. Advisory only — extend_retention
    re-reads the sizes from the DB and charges by that authoritative number.
    """
    return billing_service.estimate_retention_extension(
        sum(a.size_bytes for a in submission.attachments)
    )


def _deadline_before(moment: datetime) -> ColumnElement[bool]:
    """SQL predicate for `effective_deadline(submission) < moment`.

    Expressed as a branch on the extension column instead of SQL interval
    arithmetic: both cutoffs are computed in Python, so the query stays a plain
    indexable timestamp comparison and the base window can never drift out of
    sync with ATTACHMENT_RETENTION_DAYS_AFTER_GRADED.
    """
    return or_(
        and_(
            AssignmentSubmission.attachments_retain_until.is_(None),
            AssignmentSubmission.graded_at < moment - _BASE_WINDOW,
        ),
        and_(
            AssignmentSubmission.attachments_retain_until.isnot(None),
            AssignmentSubmission.attachments_retain_until < moment,
        ),
    )


def expired_attachments_condition(now: datetime) -> ColumnElement[bool]:
    """Rows whose retention window has fully elapsed — the purge selector."""
    return and_(AssignmentSubmission.graded_at.isnot(None), _deadline_before(now))


def reminder_due_condition(now: datetime) -> ColumnElement[bool]:
    """Graded submissions entering the reminder window (deadline within the next
    RETENTION_REMINDER_DAYS_BEFORE days and not yet past) that have not been
    mailed about this window yet."""
    horizon = now + timedelta(days=RETENTION_REMINDER_DAYS_BEFORE)
    return and_(
        AssignmentSubmission.graded_at.isnot(None),
        AssignmentSubmission.retention_reminder_sent_at.is_(None),
        _deadline_before(horizon),
        # Already-expired submissions are the purge job's business, not the
        # reminder's — mailing "your files are going" after they are gone is noise.
        ~_deadline_before(now),
    )


# ── Async (FastAPI) ──────────────────────────────────────────────────────────


async def extend_retention(
    db: AsyncSession, submission: AssignmentSubmission, user_id: UUID
) -> datetime:
    """Buy one RETENTION_EXTENSION_DAYS extension for `submission`.

    Teacher-initiated, so it follows the ordinary RESERVE → charge/release path:
    the hold is opened before the row is touched and only converted to a charge
    once the new deadline is committed. Returns the new effective deadline.
    """
    if submission.graded_at is None:
        raise HTTPException(status_code=409, detail={"code": "submission_not_graded"})

    # Count and size in one round-trip, over EVERY kind: the purge deletes both
    # submission and feedback files, so the price must cover what actually goes.
    # Read at click time, so files uploaded since the last extension are billed.
    row = (
        await db.execute(
            select(
                func.count(AssignmentAttachment.id),
                func.coalesce(func.sum(AssignmentAttachment.size_bytes), 0),
            ).where(AssignmentAttachment.submission_id == submission.id)
        )
    ).one()
    attachment_count, total_bytes = int(row[0]), int(row[1])
    if not attachment_count:
        # Nothing left to keep — the purge already ran, or nothing was uploaded.
        # Refuse before reserving so the teacher is never charged for a no-op.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "attachments_already_removed",
                "expires_at": _isoformat(effective_deadline(submission)),
            },
        )

    amount = billing_service.estimate_retention_extension(total_bytes)
    # Must fit CreditTransaction.ref_id (String(64)): 10 + 36 + 1 + 8 = 55.
    billing_ref = f"retention:{submission.id}:{uuid4().hex[:8]}"
    if not await billing_service.reserve_credits(
        db, user_id, amount, billing_ref, CreditOperation.RETENTION_EXTEND
    ):
        balance = await billing_service.get_balance(db, user_id)
        raise HTTPException(
            status_code=402,
            detail={
                "code": "insufficient_credits",
                "required": amount,
                "available": balance["available"],
            },
        )

    try:
        # graded_at was checked above, so the deadline is never None here.
        current = effective_deadline(submission) or submission.graded_at
        submission.attachments_retain_until = current + timedelta(days=RETENTION_EXTENSION_DAYS)
        # The extension opens a new retention window, which earns its own
        # reminder shortly before the new deadline.
        submission.retention_reminder_sent_at = None
        await db.commit()
    except Exception:
        await db.rollback()
        await billing_service.release_credits(db, user_id, amount, billing_ref)
        raise

    await billing_service.charge_credits(
        db, user_id, amount, billing_ref, CreditOperation.RETENTION_EXTEND
    )
    logger.info(
        "retention_extended",
        submission_id=str(submission.id),
        expires_at=submission.attachments_retain_until.isoformat(),
        credits=amount,
    )
    return submission.attachments_retain_until


# ── Sync (Celery) ────────────────────────────────────────────────────────────


def sync_mark_reminder_sent(submission: AssignmentSubmission) -> None:
    """Flip the one-shot reminder guard. Caller commits."""
    submission.retention_reminder_sent_at = datetime.now(timezone.utc)
