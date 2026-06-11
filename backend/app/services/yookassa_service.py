"""YooKassa API client (httpx, no SDK) — one-time credit-package payments.

Only two calls are needed: create a redirect-confirmation payment and fetch a
payment by id. Authentication is HTTP Basic (shop_id:secret_key); creation
idempotency rides on the Idempotence-Key header (our Payment.idempotence_key),
so a network retry can never produce a second charge. The webhook handler
authenticates events by re-fetching the payment via get_payment — the webhook
body itself is never trusted.
"""
from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()

_TIMEOUT = 20.0


class YooKassaError(RuntimeError):
    """Network failure or unexpected YooKassa API response."""


class YooKassaNotFound(YooKassaError):
    """Payment id unknown to YooKassa (404)."""


def _auth() -> httpx.BasicAuth:
    return httpx.BasicAuth(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY)


def is_configured() -> bool:
    return bool(settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY)


def _receipt(customer_email: str, credits: int, amount_value: str) -> dict[str, Any]:
    # 54-ФЗ receipt for ИП: one service item, vat code from env.
    return {
        "customer": {"email": customer_email},
        "items": [
            {
                "description": f"Пакет {credits} кредитов",
                "quantity": "1.00",
                "amount": {"value": amount_value, "currency": "RUB"},
                "vat_code": settings.YOOKASSA_VAT_CODE,
                "payment_subject": "service",
                "payment_mode": "full_payment",
            }
        ],
    }


def base_return_url() -> str:
    return settings.YOOKASSA_RETURN_URL or f"{settings.FRONTEND_URL}/billing"


async def create_payment(
    *,
    amount_rub: str,
    description: str,
    idempotence_key: str,
    metadata: dict[str, str],
    credits: int,
    customer_email: str,
    return_url: str,
) -> dict[str, Any]:
    """POST /payments → the created payment object (incl. confirmation_url)."""
    body: dict[str, Any] = {
        "amount": {"value": amount_rub, "currency": "RUB"},
        "capture": True,
        "confirmation": {"type": "redirect", "return_url": return_url},
        "description": description,
        "metadata": metadata,
    }
    if settings.YOOKASSA_SEND_RECEIPT:
        body["receipt"] = _receipt(customer_email, credits, amount_rub)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{settings.YOOKASSA_API_URL}/payments",
                json=body,
                auth=_auth(),
                headers={"Idempotence-Key": idempotence_key},
            )
    except httpx.HTTPError as exc:
        raise YooKassaError(f"YooKassa create failed: {exc}") from exc
    if resp.status_code >= 400:
        logger.error(
            "yookassa_create_failed", status=resp.status_code, body=resp.text[:500]
        )
        raise YooKassaError(f"YooKassa create failed: HTTP {resp.status_code}")
    return resp.json()


async def get_payment(yookassa_payment_id: str) -> dict[str, Any]:
    """GET /payments/{id} — the authoritative payment state."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                f"{settings.YOOKASSA_API_URL}/payments/{yookassa_payment_id}",
                auth=_auth(),
            )
    except httpx.HTTPError as exc:
        raise YooKassaError(f"YooKassa fetch failed: {exc}") from exc
    if resp.status_code == 404:
        raise YooKassaNotFound(yookassa_payment_id)
    if resp.status_code >= 400:
        logger.error(
            "yookassa_fetch_failed", status=resp.status_code, body=resp.text[:500]
        )
        raise YooKassaError(f"YooKassa fetch failed: HTTP {resp.status_code}")
    return resp.json()
