"""Reading and writing the do-not-send list.

Writes come from the Resend delivery webhook and run in a prefork Celery worker,
so they are sync (psycopg2 Session). Reads happen in both worlds — the webhook
task and the registration/change-email request path — hence the sync/async pair
on `is_suppressed`. Clearing has no async caller: the only request-path flow that
could want it (confirm-email-change) is already barred from reaching a suppressed
address by the gate in front of it.

Two levels of idempotency, deliberately separate:

  * *event* level — a redelivery of the SAME svix-id is a complete no-op. Guarded
    in Redis with SET NX (`seen_event`), mirroring email_token_service.
  * *address* level — an independent later bounce for an address already
    suppressed bumps `hits` and refreshes `occurred_at` instead of inserting a
    duplicate row.

Addresses are normalized to lowercase on the way in and on the way out, so the
unique index on `email` doubles as the case-insensitive lookup key. Only the
domain of an address is case-insensitive per RFC 5321, but every provider we
target treats the local part that way too, and a user who signed up as
`Bob@x.ru` must not dodge his own bounce record by typing `bob@x.ru`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import redis as _sync_redis
import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.constants import EMAIL_EVENT_DEDUP_TTL_SECONDS
from app.models.email_suppression import EmailSuppression, SuppressionReason
from app.models.user import User

logger = structlog.get_logger()

# Reasons that stop future sending. `manual` is included: an operator adding a
# row means the same thing. Kept as a tuple so it can go straight into an IN().
BLOCKING_REASONS: tuple[SuppressionReason, ...] = (
    SuppressionReason.hard_bounce,
    SuppressionReason.complaint,
    SuppressionReason.manual,
)


def normalize(email: str) -> str:
    return email.strip().lower()


def _event_key(event_id: str) -> str:
    return f"email_event_seen:{event_id}"


def seen_event(redis: "_sync_redis.Redis", event_id: str) -> bool:
    """True if `event_id` was already processed; marks it seen otherwise.

    Sync — called from the webhook task with the sync Redis client. SET NX is
    atomic, so two workers handed the same redelivery cannot both proceed.
    """
    fresh = redis.set(_event_key(event_id), "1", nx=True, ex=EMAIL_EVENT_DEDUP_TTL_SECONDS)
    return not fresh


# ── Reads ────────────────────────────────────────────────────────────────────


def sync_is_suppressed(db: Session, email: str) -> bool:
    return (
        db.scalar(
            select(EmailSuppression.id).where(
                EmailSuppression.email == normalize(email),
                EmailSuppression.reason.in_(BLOCKING_REASONS),
            )
        )
        is not None
    )


async def is_suppressed(db: AsyncSession, email: str) -> bool:
    return (
        await db.scalar(
            select(EmailSuppression.id).where(
                EmailSuppression.email == normalize(email),
                EmailSuppression.reason.in_(BLOCKING_REASONS),
            )
        )
    ) is not None


# ── Writes (sync only — the webhook task owns them) ─────────────────────────


def _find_user(db: Session, email: str) -> User | None:
    """The live account holding `email`, or None.

    select(), not Session.get(): the global soft-delete filter hooks ORM SELECTs
    and is what makes a purged/soft-deleted account invisible here — get() would
    bypass it and hand back a row we must not touch.
    """
    return db.scalar(select(User).where(func.lower(User.email) == normalize(email)))


def record_event(
    db: Session,
    *,
    email: str,
    reason: SuppressionReason,
    detail: str | None = None,
    provider_message_id: str | None = None,
    occurred_at: datetime | None = None,
) -> bool:
    """Suppress `email` and flag its account. Returns True if a row was created.

    An address already on the list gets `hits` bumped and its reason/detail
    refreshed to the latest event — a complaint after a bounce is still the more
    recent truth about the address. Commits; safe to call for an address that
    belongs to no account (the suppression row is still the useful part).
    """
    address = normalize(email)
    when = occurred_at or datetime.now(timezone.utc)

    # One atomic statement, not SELECT-then-INSERT: the worker runs this task
    # concurrently, and two events for the same address arriving together made
    # the loser die on the unique index (observed, not theoretical).
    stmt = (
        pg_insert(EmailSuppression)
        .values(
            email=address,
            reason=reason,
            detail=detail,
            provider_message_id=provider_message_id,
            occurred_at=when,
            hits=1,
        )
        .on_conflict_do_update(
            index_elements=[EmailSuppression.email],
            set_={
                "reason": reason,
                "detail": detail,
                "provider_message_id": provider_message_id,
                "occurred_at": when,
                "hits": EmailSuppression.hits + 1,
                # onupdate=func.now() applies to ORM/Core UPDATE, not to the
                # DO UPDATE arm of an upsert, so it is set by hand.
                "updated_at": func.now(),
            },
        )
        .returning(EmailSuppression.hits)
    )
    hits = db.scalar(stmt)
    created = hits == 1

    user = _find_user(db, address)
    if user is not None:
        user.email_bounced_at = when
        user.email_bounce_reason = reason.value
    db.commit()

    logger.info(
        "email_suppressed",
        email=address,
        reason=reason.value,
        created=created,
        hits=hits,
        user_found=user is not None,
    )
    return created


def sync_clear_for_email(db: Session, email: str) -> None:
    """Drop `email` from the list and clear its account's bounce flag.

    Called on a delivered event and after a confirmed email change — in both
    cases the address has just proved it accepts mail. Commits.

    A complaint is never lifted this way. Providers can deliver events out of
    order, and "delivered" arriving after "complained" must not put someone who
    pressed the spam button back on the send list; only a bounce (the mailbox
    was missing and now isn't) is retractable by evidence of delivery.
    """
    address = normalize(email)
    row = db.scalar(select(EmailSuppression).where(EmailSuppression.email == address))
    if row is not None and row.reason is SuppressionReason.complaint:
        db.rollback()
        return
    if row is not None:
        # Core DELETE rather than session.delete(row): a concurrent clear for the
        # same address would leave the ORM object stale and raise on flush.
        db.execute(delete(EmailSuppression).where(EmailSuppression.email == address))

    user = _find_user(db, address)
    cleared_user = False
    if user is not None and user.email_bounced_at is not None:
        user.email_bounced_at = None
        user.email_bounce_reason = None
        cleared_user = True

    if row is not None or cleared_user:
        db.commit()
        logger.info("email_suppression_cleared", email=address, row_removed=row is not None)
    else:
        db.rollback()
