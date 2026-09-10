"""Outbound mail + inbound delivery feedback, both on the dedicated
`celery_email` queue so neither competes with the video/vision pipelines for
concurrency.

`send_email` renders a Jinja2 template and posts to the provider. Retriable
provider failures (network / 5xx) raise EmailDeliveryError and are retried with
exponential backoff; provider 4xx is permanent and fails fast. A suppressed
address is permanent too — the send is dropped before the provider is contacted.

`handle_email_delivery_event` is the other direction: the Resend webhook (see
routers/webhooks_email.py) verifies the signature, returns 200 immediately and
hands the parsed event here.

Sync-only, like every task module: psycopg2 Session and the sync Redis client,
never AsyncSession (greenlet deadlock on a prefork worker).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from app.celery_app import celery_app
from app.constants import EMAIL_SEND_MAX_RETRIES, EMAIL_SEND_RETRY_BACKOFF
from app.models.email_suppression import SuppressionReason
from app.services import email_suppression_service
from app.services.email_service import EmailDeliveryError, send_email_sync
from app.tasks.video_pipeline import SyncSession, _get_sync_redis

logger = structlog.get_logger()


@celery_app.task(
    bind=True,
    name="send_email",
    queue="celery_email",
    autoretry_for=(EmailDeliveryError,),
    retry_backoff=EMAIL_SEND_RETRY_BACKOFF,
    retry_kwargs={"max_retries": EMAIL_SEND_MAX_RETRIES},
    acks_late=True,
)
def send_email(
    self,
    to: str,
    subject: str,
    template_name: str,
    context: dict[str, Any],
    headers: dict[str, str] | None = None,
) -> dict:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=self.request.id, task_name=self.name)

    # The single choke point every caller routes through (auth, notifications,
    # digests, the video pipeline), so one check here covers all of them.
    # Suppression is permanent, so this returns instead of raising
    # EmailDeliveryError — a retry would mail a dead address three more times.
    with SyncSession() as db:
        suppressed = email_suppression_service.sync_is_suppressed(db, to)
    if suppressed:
        logger.warning("email_suppressed_skip", to=to, template=template_name)
        return {"status": "suppressed", "to": to}

    send_email_sync(
        to=to,
        subject=subject,
        template_name=template_name,
        context=context,
        headers=headers,
    )
    return {"status": "sent", "to": to}


# ── Inbound delivery feedback ────────────────────────────────────────────────

# Resend's bounce classification. Only a hard bounce is a permanent verdict about
# the mailbox; soft/transient ones (full mailbox, greylisting) are logged and
# nothing else, so a temporarily full inbox never costs someone their account.
_HARD_BOUNCE_TYPES = frozenset({"hard", "permanent"})


def _event_email(data: dict[str, Any]) -> str | None:
    """The recipient carried by a Resend event payload. `to` is a list for a
    normal send; a string shows up on some event shapes, so both are handled."""
    to = data.get("to")
    if isinstance(to, list):
        return next((item for item in to if isinstance(item, str) and item), None)
    if isinstance(to, str) and to:
        return to
    return None


def _event_time(payload: dict[str, Any]) -> datetime:
    raw = payload.get("created_at")
    if isinstance(raw, str):
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


@celery_app.task(
    bind=True,
    name="handle_email_delivery_event",
    queue="celery_email",
    acks_late=True,
)
def handle_email_delivery_event(self, event_id: str, payload: dict[str, Any]) -> dict:
    """Apply one Resend delivery event.

    `event_id` is the svix-id. A redelivery of the same event is a complete
    no-op — not a second `hits` bump — because Resend retries on any non-2xx and
    we would otherwise inflate the counter for a single bounce.
    """
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=self.request.id, task_name=self.name)

    if email_suppression_service.seen_event(_get_sync_redis(), event_id):
        logger.info("email_event_duplicate", event_id=event_id)
        return {"status": "duplicate", "event_id": event_id}

    event_type = str(payload.get("type") or "")
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}
    address = _event_email(data)
    if not address:
        logger.warning("email_event_no_recipient", event_id=event_id, type=event_type)
        return {"status": "ignored", "event_id": event_id}

    message_id = data.get("email_id") or data.get("id")
    message_id = str(message_id) if message_id else None
    occurred_at = _event_time(payload)

    if event_type == "email.bounced":
        bounce = data.get("bounce")
        bounce = bounce if isinstance(bounce, dict) else {}
        bounce_type = str(bounce.get("type") or "").lower()
        if bounce_type not in _HARD_BOUNCE_TYPES:
            # Transient — log the structure and leave the address alone.
            logger.info(
                "email_soft_bounce",
                event_id=event_id,
                email=address,
                bounce_type=bounce_type or "unknown",
                message_id=message_id,
            )
            return {"status": "soft_bounce", "event_id": event_id}
        with SyncSession() as db:
            email_suppression_service.record_event(
                db,
                email=address,
                reason=SuppressionReason.hard_bounce,
                detail=str(bounce.get("message") or bounce.get("subType") or "")[:2000] or None,
                provider_message_id=message_id,
                occurred_at=occurred_at,
            )
        return {"status": "suppressed", "event_id": event_id}

    if event_type == "email.complained":
        with SyncSession() as db:
            email_suppression_service.record_event(
                db,
                email=address,
                reason=SuppressionReason.complaint,
                detail="spam complaint",
                provider_message_id=message_id,
                occurred_at=occurred_at,
            )
        return {"status": "suppressed", "event_id": event_id}

    if event_type == "email.delivered":
        # Clears the flag only on the account that currently holds this exact
        # address, so a late delivered for a replaced address cannot un-warn a
        # user who has already moved on.
        with SyncSession() as db:
            email_suppression_service.sync_clear_for_email(db, address)
        return {"status": "cleared", "event_id": event_id}

    logger.info("email_event_ignored", event_id=event_id, type=event_type)
    return {"status": "ignored", "event_id": event_id}
