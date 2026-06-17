"""YooKassa payments: creation, webhook idempotency, polling settlement.

The YooKassa HTTP client is mocked at the service-function level (the routers
call module attributes of app.services.yookassa_service, so monkeypatching the
module works for both the create and the webhook/poll paths).
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import CREDIT_PACKAGES
from app.models.credit import CreditOperation
from app.models.payment import Payment, PaymentStatus
from app.models.user import User
from app.schemas.yookassa import YooKassaPayment
from app.services import billing_service, yookassa_service

pytestmark = pytest.mark.integration


def _mock_create(monkeypatch: pytest.MonkeyPatch, yk_id: str = "yk-pay-1") -> list[dict]:
    calls: list[dict] = []

    async def _fake_create(**kwargs: Any) -> YooKassaPayment:
        calls.append(kwargs)
        return YooKassaPayment.model_validate(
            {
                "id": yk_id,
                "status": "pending",
                "confirmation": {"confirmation_url": "https://yookassa.test/confirm"},
            }
        )

    monkeypatch.setattr(yookassa_service, "create_payment", _fake_create)
    return calls


def _mock_get(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    async def _fake_get(yk_id: str) -> YooKassaPayment:
        return YooKassaPayment.model_validate({"id": yk_id, "status": status})

    monkeypatch.setattr(yookassa_service, "get_payment", _fake_get)


async def _create_payment(
    client: AsyncClient, teacher_token: dict[str, str], package_key: str = "pack_50"
) -> dict:
    resp = await client.post(
        "/api/v1/billing/payments",
        json={"package_key": package_key},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    return resp.json()


async def test_create_payment_returns_confirmation_url(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _mock_create(monkeypatch)

    body = await _create_payment(client, teacher_token)
    assert body["confirmation_url"] == "https://yookassa.test/confirm"

    payment = await db_session.scalar(
        select(Payment).where(Payment.id == body["payment_id"])
    )
    assert payment is not None
    assert payment.status == PaymentStatus.pending
    assert payment.yookassa_payment_id == "yk-pay-1"
    assert payment.credits == CREDIT_PACKAGES["pack_50"]["credits"]
    assert float(payment.amount_rub) == CREDIT_PACKAGES["pack_50"]["price_rub"]
    # Idempotence-Key + per-payment return URL went to YooKassa.
    assert calls[0]["idempotence_key"] == payment.idempotence_key
    assert f"payment_id={payment.id}" in calls[0]["return_url"]


async def test_create_payment_unknown_package_400(
    client: AsyncClient, teacher_token: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/billing/payments",
        json={"package_key": "pack_999"},
        cookies=teacher_token,
    )
    assert resp.status_code == 400


async def test_webhook_double_delivery_credits_once(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-delivered payment.succeeded must be a no-op: credits granted exactly
    once, exactly one PURCHASE ledger row."""
    # Snapshot: the second delivery's no-op path rolls back, expiring ORM
    # instances — reading teacher_user.id afterwards would raise MissingGreenlet.
    uid = teacher_user.id
    _mock_create(monkeypatch)
    body = await _create_payment(client, teacher_token, "pack_200")
    _mock_get(monkeypatch, "succeeded")

    webhook_body = {"event": "payment.succeeded", "object": {"id": "yk-pay-1"}}
    first = await client.post("/api/v1/billing/webhooks/yookassa", json=webhook_body)
    assert first.status_code == 200
    second = await client.post("/api/v1/billing/webhooks/yookassa", json=webhook_body)
    assert second.status_code == 200

    balance = await billing_service.get_balance(db_session, uid)
    assert balance["balance"] == CREDIT_PACKAGES["pack_200"]["credits"]

    history = await billing_service.get_transaction_history(db_session, uid)
    purchases = [t for t in history if t.operation == CreditOperation.PURCHASE]
    assert len(purchases) == 1
    assert purchases[0].delta == CREDIT_PACKAGES["pack_200"]["credits"]
    assert purchases[0].ref_id == body["payment_id"]

    payment = await db_session.scalar(
        select(Payment).where(Payment.id == body["payment_id"])
    )
    assert payment.status == PaymentStatus.succeeded


async def test_webhook_does_not_trust_body(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A forged 'succeeded' notification must not credit anything when the
    YooKassa API says the payment is still pending."""
    _mock_create(monkeypatch)
    await _create_payment(client, teacher_token)
    _mock_get(monkeypatch, "pending")  # authoritative state disagrees with body

    resp = await client.post(
        "/api/v1/billing/webhooks/yookassa",
        json={"event": "payment.succeeded", "object": {"id": "yk-pay-1"}},
    )
    assert resp.status_code == 200

    balance = await billing_service.get_balance(db_session, teacher_user.id)
    assert balance["balance"] == 0


async def test_webhook_unknown_payment_is_acknowledged(client: AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/billing/webhooks/yookassa",
        json={"event": "payment.succeeded", "object": {"id": "yk-foreign"}},
    )
    assert resp.status_code == 200


async def test_poll_endpoint_settles_pending_payment(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /payments/{id} pulls the authoritative status so local flows work
    without a publicly reachable webhook; settlement stays idempotent."""
    _mock_create(monkeypatch)
    body = await _create_payment(client, teacher_token)
    _mock_get(monkeypatch, "succeeded")

    resp = await client.get(
        f"/api/v1/billing/payments/{body['payment_id']}", cookies=teacher_token
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "succeeded"

    balance = await billing_service.get_balance(db_session, teacher_user.id)
    assert balance["balance"] == CREDIT_PACKAGES["pack_50"]["credits"]

    # Poll again — no double grant.
    await client.get(
        f"/api/v1/billing/payments/{body['payment_id']}", cookies=teacher_token
    )
    balance2 = await billing_service.get_balance(db_session, teacher_user.id)
    assert balance2["balance"] == balance["balance"]


async def test_payment_canceled_marks_status(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_create(monkeypatch)
    body = await _create_payment(client, teacher_token)
    _mock_get(monkeypatch, "canceled")

    resp = await client.get(
        f"/api/v1/billing/payments/{body['payment_id']}", cookies=teacher_token
    )
    assert resp.json()["status"] == "canceled"
    balance = await billing_service.get_balance(db_session, teacher_user.id)
    assert balance["balance"] == 0


async def test_payments_list_scoped_to_owner(
    client: AsyncClient,
    teacher_token: dict[str, str],
    student_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _mock_create(monkeypatch)
    await _create_payment(client, teacher_token)

    mine = await client.get("/api/v1/billing/payments", cookies=teacher_token)
    assert mine.status_code == 200
    assert len(mine.json()) == 1

    others = await client.get("/api/v1/billing/payments", cookies=student_token)
    assert others.status_code == 200
    assert others.json() == []
