"""Resend delivery-event webhook.

Same shape as the YooKassa webhook: authenticity is settled before the body is
looked at, the response is a fast 200, and every bit of work happens in a sync
Celery task. Carries no auth dependency, so it sits outside the cookie/CSRF
double-submit check by construction — nothing global is disabled for it.
"""

from __future__ import annotations

import json

import structlog
from fastapi import APIRouter, Header, HTTPException, Request, status

from app.config import settings
from app.services.webhook_security import verify_svix_signature
from app.tasks.email_pipeline import handle_email_delivery_event

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


@router.post("/resend")
async def resend_webhook(
    request: Request,
    svix_id: str | None = Header(default=None, alias="svix-id"),
    svix_timestamp: str | None = Header(default=None, alias="svix-timestamp"),
    svix_signature: str | None = Header(default=None, alias="svix-signature"),
) -> dict:
    """Accept one signed Resend event and hand it to the worker.

    An unconfigured RESEND_WEBHOOK_SECRET answers 503, not 404: Resend retries
    5xx and does not retry 404, so a deploy that lands before the secret is set
    keeps its events instead of losing them silently.
    """
    if not settings.RESEND_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="webhook_not_configured",
        )

    # Raw bytes: the signature covers the exact payload, so it must be checked
    # before any parsing — a re-serialized body would not match.
    body = await request.body()
    if not verify_svix_signature(
        secret=settings.RESEND_WEBHOOK_SECRET,
        svix_id=svix_id,
        svix_timestamp=svix_timestamp,
        svix_signature=svix_signature,
        body=body,
    ):
        logger.warning("resend_webhook_bad_signature", svix_id=svix_id)
        raise HTTPException(status_code=400, detail="invalid_signature")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid_body")
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="invalid_body")

    try:
        handle_email_delivery_event.delay(svix_id, payload)
    except Exception:
        # Broker down: the event has nowhere to go, so ask Resend to bring it
        # back rather than acking a bounce we never recorded. There is no
        # reconcile sweep on this path — the provider's retry IS the backstop.
        logger.warning("resend_webhook_enqueue_failed", svix_id=svix_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="enqueue_failed",
        )

    return {"status": "accepted"}
