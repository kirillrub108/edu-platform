"""Unit tests for the YooKassa payment building blocks (no DB, no network):

  * CREDIT_PACKAGES shape (price/credits/receipt fields per sku)
  * receipt assembly from per-package attributes
  * payment_matches anti-fraud gate (amount/currency/paid/status)
  * webhook source-IP resolution + allowlist
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from starlette.requests import Request

from app.constants import CREDIT_PACKAGES
from app.schemas.yookassa import YooKassaPayment
from app.services import yookassa_service
from app.services.webhook_security import is_trusted_yookassa_ip, resolve_client_ip

pytestmark = pytest.mark.unit


def test_credit_packages_shape() -> None:
    for sku, p in CREDIT_PACKAGES.items():
        assert isinstance(p["credits"], int) and p["credits"] > 0, sku
        assert isinstance(p["price_rub"], int) and p["price_rub"] > 0, sku
        assert isinstance(p["title"], str) and p["title"], sku
        assert isinstance(p["vat_code"], int), sku
        assert isinstance(p["payment_subject"], str) and p["payment_subject"], sku
        assert isinstance(p["payment_mode"], str) and p["payment_mode"], sku


def test_receipt_uses_per_package_fields() -> None:
    receipt = yookassa_service._receipt(
        customer_email="buyer@example.com",
        title="50 кредитов",
        amount_value="190.00",
        vat_code=2,
        payment_subject="service",
        payment_mode="full_payment",
    )
    assert receipt["customer"]["email"] == "buyer@example.com"
    item = receipt["items"][0]
    assert item["description"] == "50 кредитов"
    assert item["quantity"] == "1.00"
    assert item["amount"] == {"value": "190.00", "currency": "RUB"}
    assert item["vat_code"] == 2
    assert item["payment_subject"] == "service"
    assert item["payment_mode"] == "full_payment"


def _payment(
    *, status: str = "succeeded", paid: bool = True, value: str = "190.00", currency: str = "RUB"
) -> YooKassaPayment:
    return YooKassaPayment.model_validate(
        {
            "id": "yk-1",
            "status": status,
            "paid": paid,
            "amount": {"value": value, "currency": currency},
        }
    )


def test_payment_matches_accepts_exact_paid_rub_success() -> None:
    assert yookassa_service.payment_matches(_payment(), Decimal("190.00")) is True


def test_payment_matches_rejects_amount_mismatch() -> None:
    assert yookassa_service.payment_matches(_payment(value="1.00"), Decimal("190.00")) is False


def test_payment_matches_rejects_wrong_currency() -> None:
    assert yookassa_service.payment_matches(_payment(currency="USD"), Decimal("190.00")) is False


def test_payment_matches_rejects_unpaid() -> None:
    assert yookassa_service.payment_matches(_payment(paid=False), Decimal("190.00")) is False


def test_payment_matches_rejects_non_succeeded() -> None:
    assert yookassa_service.payment_matches(_payment(status="pending"), Decimal("190.00")) is False


def _request(client: tuple[str, int] | None, headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/billing/webhooks/yookassa",
            "client": client,
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
    )


def test_is_trusted_yookassa_ip() -> None:
    assert is_trusted_yookassa_ip("185.71.76.5") is True
    assert is_trusted_yookassa_ip("8.8.8.8") is False
    assert is_trusted_yookassa_ip(None) is False
    assert is_trusted_yookassa_ip("not-an-ip") is False


def test_resolve_ip_reads_xff_behind_trusted_proxy() -> None:
    req = _request(("127.0.0.1", 5), {"x-forwarded-for": "185.71.76.5"})
    assert resolve_client_ip(req) == "185.71.76.5"


def test_resolve_ip_ignores_xff_from_untrusted_peer() -> None:
    req = _request(("8.8.8.8", 5), {"x-forwarded-for": "185.71.76.5"})
    assert resolve_client_ip(req) == "8.8.8.8"


def test_resolve_ip_takes_rightmost_nonproxy_hop() -> None:
    req = _request(("127.0.0.1", 5), {"x-forwarded-for": "185.71.76.5, 10.0.0.2"})
    assert resolve_client_ip(req) == "185.71.76.5"
