"""send_email Celery task — routed to the dedicated `celery_email` queue so
mail delivery never competes with the video/vision pipelines for concurrency.

Sync-only (like every task module): it calls `email_service.send_email_sync`,
which renders a Jinja2 template and posts to the provider. Retriable provider
failures (network / 5xx) raise EmailDeliveryError and are retried with
exponential backoff; provider 4xx is permanent and fails fast.
"""

from __future__ import annotations

from typing import Any

import structlog

from app.celery_app import celery_app
from app.constants import EMAIL_SEND_MAX_RETRIES, EMAIL_SEND_RETRY_BACKOFF
from app.services.email_service import EmailDeliveryError, send_email_sync

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
) -> dict:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=self.request.id, task_name=self.name)
    send_email_sync(to=to, subject=subject, template_name=template_name, context=context)
    return {"status": "sent", "to": to}
