"""Unit tests for the YooKassa HTTP client (app.services.yookassa_service).

All traffic goes through httpx.MockTransport — no socket is ever opened. What
matters here is money-safety: the Idempotence-Key must ride along unchanged on
every retry, 4xx must never be retried, and an unparsable body must surface as
a domain error instead of a half-built payment object.
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator, Callable

import httpx
import pytest

from app.config import settings
from app.services import yookassa_service as yk

pytestmark = pytest.mark.unit

_OK_BODY = {
    "id": "2f0-abc",
    "status": "pending",
    "paid": False,
    "amount": {"value": "190.00", "currency": "RUB"},
    "confirmation": {"type": "redirect", "confirmation_url": "https://yoomoney/pay/2f0-abc"},
}

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture()
async def install_async_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Callable[[Handler], list[httpx.Request]]]:
    """Swap the module-global client for one bound to a MockTransport and
    return the list that records every outgoing request."""
    created: list[httpx.AsyncClient] = []

    def _install(handler: Handler) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def _recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        client = httpx.AsyncClient(
            base_url="https://api.yookassa.test/v3/",
            transport=httpx.MockTransport(_recording),
        )
        created.append(client)
        monkeypatch.setattr(yk, "_client", client)
        return seen

    yield _install

    for client in created:
        await client.aclose()


@pytest.fixture()
def install_sync_client(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[Handler], list[httpx.Request]]:
    """`get_payment_sync` builds a short-lived httpx.Client per call, so the
    class itself is swapped for a factory that injects the mock transport."""
    real_client = httpx.Client

    def _install(handler: Handler) -> list[httpx.Request]:
        seen: list[httpx.Request] = []

        def _recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        def _factory(**kwargs: Any) -> httpx.Client:
            return real_client(transport=httpx.MockTransport(_recording), **kwargs)

        monkeypatch.setattr(yk.httpx, "Client", _factory)
        return seen

    return _install


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep retry tests instant and independent of wall-clock time."""
    monkeypatch.setattr(yk, "YOOKASSA_RETRY_BACKOFF", 0.0)


def _json_handler(status: int, body: dict[str, Any] | str) -> Handler:
    def _handler(_request: httpx.Request) -> httpx.Response:
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)

    return _handler


# ── client lifecycle ──────────────────────────────────────────────────────────


async def test_get_client_is_a_configured_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yk, "_client", None)
    monkeypatch.setattr(settings, "YOOKASSA_API_URL", "https://api.yookassa.test/v3")
    monkeypatch.setattr(settings, "YOOKASSA_SHOP_ID", "shop-1")
    monkeypatch.setattr(settings, "YOOKASSA_SECRET_KEY", "secret-1")

    client = yk.get_client()
    try:
        assert yk.get_client() is client  # built once, reused
        # The trailing slash keeps relative paths under /v3 instead of the root.
        assert str(client.base_url) == "https://api.yookassa.test/v3/"
        assert client.timeout.connect == yk.YOOKASSA_CONNECT_TIMEOUT
        assert client.timeout.read == yk.YOOKASSA_READ_TIMEOUT
    finally:
        await yk.close_client()

    assert yk._client is None


async def test_close_client_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(yk, "_client", None)
    await yk.close_client()
    assert yk._client is None


def test_is_configured_requires_both_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "YOOKASSA_SHOP_ID", "shop-1")
    monkeypatch.setattr(settings, "YOOKASSA_SECRET_KEY", "")
    assert yk.is_configured() is False

    monkeypatch.setattr(settings, "YOOKASSA_SECRET_KEY", "secret-1")
    assert yk.is_configured() is True


def test_base_return_url_falls_back_to_frontend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "YOOKASSA_RETURN_URL", "")
    monkeypatch.setattr(settings, "FRONTEND_URL", "https://edllm.test")
    assert yk.base_return_url() == "https://edllm.test/billing"

    monkeypatch.setattr(settings, "YOOKASSA_RETURN_URL", "https://edllm.test/thanks")
    assert yk.base_return_url() == "https://edllm.test/thanks"


# ── create_payment ────────────────────────────────────────────────────────────


async def _create(**overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "amount_rub": "190.00",
        "description": "50 кредитов",
        "idempotence_key": "idem-key-1",
        "metadata": {"user_id": "u-1", "sku": "credits_50"},
        "title": "50 кредитов",
        "vat_code": 1,
        "payment_subject": "service",
        "payment_mode": "full_payment",
        "customer_email": "buyer@example.com",
        "return_url": "https://edllm.test/billing",
    }
    kwargs.update(overrides)
    return await yk.create_payment(**kwargs)


async def test_create_payment_sends_idempotence_key_and_capture(
    install_async_client: Callable[[Handler], list[httpx.Request]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "YOOKASSA_SEND_RECEIPT", False)
    seen = install_async_client(_json_handler(200, _OK_BODY))

    payment = await _create()

    assert payment.id == "2f0-abc"
    assert payment.confirmation is not None
    assert payment.confirmation.confirmation_url == "https://yoomoney/pay/2f0-abc"
    assert len(seen) == 1
    assert seen[0].headers["Idempotence-Key"] == "idem-key-1"
    body = json.loads(seen[0].content)
    assert body["capture"] is True
    assert body["amount"] == {"value": "190.00", "currency": "RUB"}
    assert body["metadata"] == {"user_id": "u-1", "sku": "credits_50"}
    assert body["confirmation"] == {
        "type": "redirect",
        "return_url": "https://edllm.test/billing",
    }
    assert "receipt" not in body  # 54-ФЗ receipt is opt-in


async def test_create_payment_attaches_receipt_when_enabled(
    install_async_client: Callable[[Handler], list[httpx.Request]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "YOOKASSA_SEND_RECEIPT", True)
    seen = install_async_client(_json_handler(200, _OK_BODY))

    await _create(vat_code=2)

    receipt = json.loads(seen[0].content)["receipt"]
    assert receipt["customer"]["email"] == "buyer@example.com"
    assert receipt["items"][0]["amount"] == {"value": "190.00", "currency": "RUB"}
    assert receipt["items"][0]["vat_code"] == 2


async def test_create_payment_does_not_retry_a_4xx(
    install_async_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    """Re-POSTing on a rejection is how double charges happen — 4xx must fail fast."""
    seen = install_async_client(_json_handler(400, {"description": "invalid amount"}))

    with pytest.raises(yk.YooKassaError, match="create failed: HTTP 400"):
        await _create()
    assert len(seen) == 1


async def test_create_payment_rejects_malformed_body(
    install_async_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    install_async_client(_json_handler(200, "<html>maintenance</html>"))

    with pytest.raises(yk.YooKassaError, match="malformed payload"):
        await _create()


async def test_create_payment_retries_transport_errors_with_same_key(
    install_async_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    attempts = {"n": 0}

    def _flaky(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ConnectTimeout("upstream timed out")
        return httpx.Response(200, json=_OK_BODY)

    seen = install_async_client(_flaky)

    payment = await _create()

    assert payment.id == "2f0-abc"
    assert len(seen) == 2
    # The retry must be byte-identical, otherwise idempotency is lost.
    assert {r.headers["Idempotence-Key"] for r in seen} == {"idem-key-1"}


async def test_create_payment_gives_up_after_the_retry_budget(
    install_async_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    def _always_down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    seen = install_async_client(_always_down)

    with pytest.raises(yk.YooKassaError, match="failed after"):
        await _create()
    assert len(seen) == yk.YOOKASSA_MAX_RETRIES + 1


# ── get_payment (async) ───────────────────────────────────────────────────────


async def test_get_payment_returns_authoritative_state(
    install_async_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    seen = install_async_client(
        _json_handler(200, {**_OK_BODY, "status": "succeeded", "paid": True})
    )

    payment = await yk.get_payment("2f0-abc")

    assert (payment.status, payment.paid) == ("succeeded", True)
    assert seen[0].url.path.endswith("/v3/payments/2f0-abc")


async def test_get_payment_maps_404_to_not_found(
    install_async_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    install_async_client(_json_handler(404, {"code": "not_found"}))

    with pytest.raises(yk.YooKassaNotFound, match="missing-id"):
        await yk.get_payment("missing-id")


async def test_get_payment_raises_on_server_error(
    install_async_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    seen = install_async_client(_json_handler(500, {"code": "internal"}))

    with pytest.raises(yk.YooKassaError, match="fetch failed: HTTP 500"):
        await yk.get_payment("2f0-abc")
    assert len(seen) == 1  # HTTP status is never retried, only transport errors


# ── get_payment_sync (Celery path) ────────────────────────────────────────────


def test_get_payment_sync_returns_payment(
    install_sync_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    seen = install_sync_client(
        _json_handler(200, {**_OK_BODY, "status": "succeeded", "paid": True})
    )

    payment = yk.get_payment_sync("2f0-abc")

    assert payment.status == "succeeded"
    assert seen[0].url.path.endswith("/payments/2f0-abc")


def test_get_payment_sync_maps_404_to_not_found(
    install_sync_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    install_sync_client(_json_handler(404, {"code": "not_found"}))

    with pytest.raises(yk.YooKassaNotFound):
        yk.get_payment_sync("missing-id")


def test_get_payment_sync_raises_on_server_error(
    install_sync_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    seen = install_sync_client(_json_handler(502, {"code": "bad_gateway"}))

    with pytest.raises(yk.YooKassaError, match="fetch failed: HTTP 502"):
        yk.get_payment_sync("2f0-abc")
    assert len(seen) == 1


def test_get_payment_sync_rejects_malformed_body(
    install_sync_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    install_sync_client(_json_handler(200, "not json at all"))

    with pytest.raises(yk.YooKassaError, match="malformed payload"):
        yk.get_payment_sync("2f0-abc")


def test_get_payment_sync_retries_then_succeeds(
    install_sync_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    attempts = {"n": 0}

    def _flaky(_request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ReadTimeout("slow upstream")
        return httpx.Response(200, json=_OK_BODY)

    seen = install_sync_client(_flaky)

    assert yk.get_payment_sync("2f0-abc").id == "2f0-abc"
    assert len(seen) == 2


def test_get_payment_sync_gives_up_after_the_retry_budget(
    install_sync_client: Callable[[Handler], list[httpx.Request]],
) -> None:
    def _always_down(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    seen = install_sync_client(_always_down)

    with pytest.raises(yk.YooKassaError, match="failed after"):
        yk.get_payment_sync("2f0-abc")
    assert len(seen) == yk.YOOKASSA_MAX_RETRIES + 1
