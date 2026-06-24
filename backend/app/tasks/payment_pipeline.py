"""Settle YooKassa payments off the webhook request path + reconcile stuck ones.

The webhook only verifies the source IP and enqueues `process_yookassa_payment`,
then returns 200 immediately so YooKassa stops its 24h retries. The task re-fetches
the authoritative payment (the notification body is never trusted), locates the
local Payment row and credits the package exactly once.

Because returning 200 forgoes YooKassa's redelivery, `reconcile_pending_payments`
(beat, every RECONCILE_INTERVAL_MINUTES) is the backstop for the case where the
webhook 200'd but the task never ran AND the user never polled: it re-queries
stuck `pending` payments and drives them through the SAME settlement path.

Sync-only: like every task in this package it uses the psycopg2 SyncSession and
the sync YooKassa client — never an AsyncSession or the async httpx client.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import settings
from app.constants import (
    PAYMENT_STUCK_ALERT_BATCH,
    PAYMENT_STUCK_ALERT_EMAIL,
    PAYMENT_STUCK_ALERT_MINUTES,
    PAYMENT_TASK_MAX_RETRIES,
    PAYMENT_TASK_RETRY_BACKOFF,
    PAYMENT_TASK_RETRY_MAX_BACKOFF,
    RECONCILE_BATCH_SIZE,
    RECONCILE_MAX_AGE_HOURS,
    RECONCILE_MIN_AGE_MINUTES,
)
from app.models.payment import Payment, PaymentStatus
from app.services import billing_service, yookassa_service
from app.tasks.email_pipeline import send_email
from app.tasks.video_pipeline import SyncSession

logger = structlog.get_logger()


def _local_payment_id(yk: yookassa_service.YooKassaPayment) -> UUID | None:
    """Our Payment.id, echoed back by YooKassa in metadata.payment_id. Trusting
    it (a value we set, returned by the authoritative GET) lets settlement find
    the row even when the webhook beats the create endpoint's id commit."""
    raw = (yk.metadata or {}).get("payment_id")
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except ValueError:
        return None


def _settle_payment(db: Session, yk: yookassa_service.YooKassaPayment, event: str) -> str:
    """THE single money path — shared by the webhook task and the reconcile sweep,
    never duplicated.

    Locks the local row FOR UPDATE, then applies the same status guard and the
    payment_matches anti-fraud gate before crediting via billing_service. So a
    concurrent webhook + reconcile (or a redelivery) can never double-credit:
    whoever wins the lock settles, the other sees a terminal status and no-ops.
    Returns a short outcome string for logging/metrics.
    """
    local_id = _local_payment_id(yk)
    payment: Payment | None = None
    if local_id is not None:
        payment = db.scalar(select(Payment).where(Payment.id == local_id).with_for_update())
    if payment is None:
        payment = db.scalar(
            select(Payment).where(Payment.yookassa_payment_id == yk.id).with_for_update()
        )
    if payment is None:
        logger.warning("payment_settle_unknown", yookassa_payment_id=yk.id)
        return "unknown"

    if event == "refund.succeeded":
        changed = billing_service.sync_mark_payment_refunded(db, payment)
        logger.info("payment_settle_refunded", payment_id=str(payment.id), changed=changed)
        return "refunded" if changed else "noop"

    if payment.status != PaymentStatus.pending:
        db.rollback()
        return "noop"

    if yk.status == "canceled":
        billing_service.sync_mark_payment_canceled(db, payment)
        logger.info("payment_settle_canceled", payment_id=str(payment.id))
        return "canceled"

    if yk.status == "succeeded":
        if not yookassa_service.payment_matches(yk, payment.amount_rub):
            db.rollback()
            logger.error(
                "payment_settle_amount_mismatch",
                payment_id=str(payment.id),
                expected=str(payment.amount_rub),
                got=(yk.amount.value if yk.amount else None),
                currency=(yk.amount.currency if yk.amount else None),
                paid=yk.paid,
            )
            return "mismatch"
        billing_service.sync_apply_purchase(db, payment, yookassa_payment_id=yk.id)
        logger.info("payment_settle_credited", payment_id=str(payment.id), credits=payment.credits)
        return "succeeded"

    # waiting_for_capture / pending / anything non-terminal — leave it.
    db.rollback()
    return yk.status


@celery_app.task(
    name="process_yookassa_payment",
    queue="quiz",
    bind=True,
    max_retries=PAYMENT_TASK_MAX_RETRIES,
)
def process_yookassa_payment(self, event: str, yookassa_payment_id: str) -> dict:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(yk_event=event, yookassa_payment_id=yookassa_payment_id)

    try:
        yk = yookassa_service.get_payment_sync(yookassa_payment_id)
    except yookassa_service.YooKassaNotFound:
        logger.warning("payment_task_not_found")
        return {"status": "not_found"}
    except yookassa_service.YooKassaError as exc:
        # Verification temporarily impossible — retry with growing backoff. The
        # reconcile sweep and the poll path are the other backstops.
        countdown = min(
            PAYMENT_TASK_RETRY_MAX_BACKOFF,
            PAYMENT_TASK_RETRY_BACKOFF * 2**self.request.retries,
        )
        raise self.retry(exc=exc, countdown=countdown)

    with SyncSession() as db:
        status = _settle_payment(db, yk, event)
    return {"status": status}


def _alert_stuck_payments(db: Session, now: datetime) -> int:
    """Flag payments still pending past PAYMENT_STUCK_ALERT_MINUTES — structured
    ERROR log (always) + optional admin email, exactly once per payment via
    alerted_at. skip_locked avoids touching a row a webhook is settling right now."""
    cutoff = now - timedelta(minutes=PAYMENT_STUCK_ALERT_MINUTES)
    stuck = (
        db.scalars(
            select(Payment)
            .where(
                Payment.status == PaymentStatus.pending,
                Payment.created_at <= cutoff,
                Payment.alerted_at.is_(None),
            )
            .limit(PAYMENT_STUCK_ALERT_BATCH)
            .with_for_update(skip_locked=True)
        )
        .all()
    )
    for payment in stuck:
        age_minutes = int((now - payment.created_at).total_seconds() // 60)
        logger.error(
            "payment_stuck_pending",
            payment_id=str(payment.id),
            yookassa_payment_id=payment.yookassa_payment_id,
            user_id=str(payment.user_id),
            age_minutes=age_minutes,
        )
        if PAYMENT_STUCK_ALERT_EMAIL and settings.ALERT_ADMIN_EMAIL:
            send_email.delay(
                to=settings.ALERT_ADMIN_EMAIL,
                subject="Edllm: платёж завис в pending",
                template_name="payment_stuck_alert.html",
                context={
                    "payment_id": str(payment.id),
                    "yookassa_payment_id": payment.yookassa_payment_id,
                    "age_minutes": age_minutes,
                },
            )
        payment.alerted_at = now
    db.commit()
    return len(stuck)


@celery_app.task(name="reconcile_pending_payments", queue="quiz")
def reconcile_pending_payments() -> dict:
    """Beat backstop: re-drive payments stuck in `pending` through the authoritative
    GET + the shared settlement path, then alert on any that stay stuck."""
    structlog.contextvars.clear_contextvars()
    now = datetime.now(timezone.utc)
    min_cutoff = now - timedelta(minutes=RECONCILE_MIN_AGE_MINUTES)  # old enough to settle
    max_cutoff = now - timedelta(hours=RECONCILE_MAX_AGE_HOURS)  # not ancient/dead

    with SyncSession() as db:
        yk_ids = list(
            db.scalars(
                select(Payment.yookassa_payment_id)
                .where(
                    Payment.status == PaymentStatus.pending,
                    Payment.yookassa_payment_id.is_not(None),
                    Payment.created_at <= min_cutoff,
                    Payment.created_at >= max_cutoff,
                )
                .limit(RECONCILE_BATCH_SIZE)
            ).all()
        )

    outcomes: dict[str, int] = {}
    for yk_id in yk_ids:
        try:
            yk = yookassa_service.get_payment_sync(yk_id)
        except yookassa_service.YooKassaNotFound:
            logger.warning("reconcile_payment_not_found", yookassa_payment_id=yk_id)
            outcomes["not_found"] = outcomes.get("not_found", 0) + 1
            continue
        except yookassa_service.YooKassaError:
            logger.warning("reconcile_fetch_failed", yookassa_payment_id=yk_id)
            outcomes["fetch_error"] = outcomes.get("fetch_error", 0) + 1
            continue
        with SyncSession() as db:
            status = _settle_payment(db, yk, f"reconcile:{yk.status}")
        outcomes[status] = outcomes.get(status, 0) + 1

    with SyncSession() as db:
        alerted = _alert_stuck_payments(db, now)

    logger.info("reconcile_done", scanned=len(yk_ids), alerted=alerted, outcomes=outcomes)
    return {"scanned": len(yk_ids), "alerted": alerted, "outcomes": outcomes}
