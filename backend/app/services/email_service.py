"""Thin transactional-email service: Jinja2 rendering + a sync send through a
provider chosen by EMAIL_PROVIDER.

Sending is **sync-only** and is invoked exclusively from the `send_email` Celery
task (prefork worker). The web side never calls a provider directly — it enqueues
`send_email.delay(...)` so a slow/unavailable provider can't block a request or
the video pipeline. Resend is implemented today; SendGrid (and any other HTTP
provider) slots in behind the same `EmailProvider` interface.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import httpx
import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.config import settings

logger = structlog.get_logger()

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates" / "email"


class EmailDeliveryError(Exception):
    """Retriable failure — a network error or a provider 5xx. The send_email
    task autoretries on this. Provider 4xx (bad request, invalid address) is a
    permanent error and raises RuntimeError instead, so it is not retried."""


@lru_cache
def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(_TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )


def render_template(template_name: str, context: dict[str, Any]) -> str:
    return _env().get_template(template_name).render(**context)


class EmailProvider(Protocol):
    def send(self, *, to: str, subject: str, html: str) -> None: ...


class ResendProvider:
    """Resend HTTP API (https://resend.com/docs/api-reference/emails)."""

    _ENDPOINT = "https://api.resend.com/emails"

    def __init__(self, api_key: str, sender: str) -> None:
        self._api_key = api_key
        self._sender = sender

    def send(self, *, to: str, subject: str, html: str) -> None:
        try:
            resp = httpx.post(
                self._ENDPOINT,
                headers={"Authorization": f"Bearer {self._api_key}"},
                json={"from": self._sender, "to": [to], "subject": subject, "html": html},
                timeout=15.0,
            )
        except httpx.HTTPError as exc:  # connect/read/timeout — transient
            raise EmailDeliveryError(f"resend request failed: {exc}") from exc
        if resp.status_code >= 500:
            raise EmailDeliveryError(f"resend 5xx: {resp.status_code} {resp.text}")
        if resp.status_code >= 400:
            raise RuntimeError(f"resend rejected email: {resp.status_code} {resp.text}")


def build_provider() -> EmailProvider:
    """Resolve the configured provider. Raises RuntimeError if it is unknown or
    missing required credentials."""
    provider = settings.EMAIL_PROVIDER.lower()
    if provider == "resend":
        if not settings.RESEND_API_KEY:
            raise RuntimeError("RESEND_API_KEY is not configured")
        return ResendProvider(settings.RESEND_API_KEY, settings.EMAIL_FROM)
    # SendGrid and friends implement EmailProvider and are wired in here.
    raise RuntimeError(f"Unsupported EMAIL_PROVIDER: {settings.EMAIL_PROVIDER}")


def send_email_sync(
    *, to: str, subject: str, template_name: str, context: dict[str, Any]
) -> None:
    """Render `template_name` with `context` and send it. Sync — call only from
    the send_email Celery task. Raises EmailDeliveryError on retriable failures."""
    html = render_template(template_name, context)
    build_provider().send(to=to, subject=subject, html=html)
    logger.info("email_sent", to=to, template=template_name, provider=settings.EMAIL_PROVIDER)
