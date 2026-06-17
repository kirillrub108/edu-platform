"""YooKassa API client (httpx, no SDK) — one-time credit-package payments.

Only two calls are needed: create a redirect-confirmation payment and fetch a
payment by id. Authentication is HTTP Basic (shop_id:secret_key); creation
idempotency rides on the Idempotence-Key header (our Payment.idempotence_key),
so a network retry can never produce a second charge. The webhook handler
authenticates events by re-fetching the payment via get_payment — the webhook
body itself is never trusted.

A single httpx.AsyncClient is shared per process (built lazily, closed in the
app lifespan). Network failures and timeouts on the idempotent calls are
retried with backoff; HTTP 4xx/5xx are surfaced as domain errors without retry.
"""
import asyncio
from typing import Any

import httpx
import structlog
from pydantic import ValidationError

from app.config import settings
from app.constants import (
    YOOKASSA_CONNECT_TIMEOUT,
    YOOKASSA_MAX_RETRIES,
    YOOKASSA_READ_TIMEOUT,
    YOOKASSA_RETRY_BACKOFF,
)
from app.schemas.yookassa import YooKassaPayment

logger = structlog.get_logger()

_client: httpx.AsyncClient | None = None


class YooKassaError(RuntimeError):
    """Network failure or unexpected YooKassa API response."""


class YooKassaNotFound(YooKassaError):
    """Payment id unknown to YooKassa (404)."""


def _get_client() -> httpx.AsyncClient:
    """The process-wide client. base_url keeps its trailing slash so relative
    paths join under /v3; auth and timeouts are baked in once."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(
            base_url=settings.YOOKASSA_API_URL.rstrip("/") + "/",
            auth=httpx.BasicAuth(settings.YOOKASSA_SHOP_ID, settings.YOOKASSA_SECRET_KEY),
            timeout=httpx.Timeout(YOOKASSA_READ_TIMEOUT, connect=YOOKASSA_CONNECT_TIMEOUT),
        )
    return _client


def get_client() -> httpx.AsyncClient:
    """Public accessor used by the app lifespan to build the client eagerly."""
    return _get_client()


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def is_configured() -> bool:
    return bool(settings.YOOKASSA_SHOP_ID and settings.YOOKASSA_SECRET_KEY)


async def _request_with_retries(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Issue an idempotent request, retrying ONLY transport/timeout errors.
    The same kwargs (incl. the Idempotence-Key header) are re-sent verbatim, so
    a retried POST /payments cannot double-charge. HTTP status is left to the
    caller — a 4xx response returns normally and is never retried here."""
    client = _get_client()
    for attempt in range(YOOKASSA_MAX_RETRIES + 1):
        try:
            return await client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            if attempt >= YOOKASSA_MAX_RETRIES:
                raise YooKassaError(
                    f"YooKassa {method} {url} failed after {attempt + 1} attempts: {exc}"
                ) from exc
            await asyncio.sleep(YOOKASSA_RETRY_BACKOFF * 2**attempt)


def _parse_payment(resp: httpx.Response, op: str) -> YooKassaPayment:
    try:
        return YooKassaPayment.model_validate(resp.json())
    except (ValueError, ValidationError) as exc:
        logger.error("yookassa_parse_failed", op=op, body=resp.text[:500])
        raise YooKassaError(f"YooKassa {op} returned a malformed payload: {exc}") from exc


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
) -> YooKassaPayment:
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

    resp = await _request_with_retries(
        "POST",
        "payments",
        json=body,
        headers={"Idempotence-Key": idempotence_key},
    )
    if resp.status_code >= 400:
        logger.error("yookassa_create_failed", status=resp.status_code, body=resp.text[:500])
        raise YooKassaError(f"YooKassa create failed: HTTP {resp.status_code}")
    return _parse_payment(resp, "create")


async def get_payment(yookassa_payment_id: str) -> YooKassaPayment:
    """GET /payments/{id} — the authoritative payment state."""
    resp = await _request_with_retries("GET", f"payments/{yookassa_payment_id}")
    if resp.status_code == 404:
        raise YooKassaNotFound(yookassa_payment_id)
    if resp.status_code >= 400:
        logger.error("yookassa_fetch_failed", status=resp.status_code, body=resp.text[:500])
        raise YooKassaError(f"YooKassa fetch failed: HTTP {resp.status_code}")
    return _parse_payment(resp, "fetch")
