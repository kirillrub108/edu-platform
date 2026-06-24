"""YooKassa payments: creation, webhook IP/enqueue, polling settlement.

The YooKassa HTTP client is mocked at the service-function level. Since the
webhook now only verifies the source IP and ENQUEUES a sync Celery task (the
task re-fetches and credits), webhook tests assert the enqueue; end-to-end
crediting / idempotency / amount-validation is covered through the async poll
path, which runs on the test's SAVEPOINT-bound session (a separate psycopg2
connection — what the eager sync task would use — can't see those rows).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from app.constants import CREDIT_PACKAGES
from app.models.credit import CreditAccount, CreditOperation, CreditTransaction
from app.models.payment import Payment, PaymentStatus
from app.models.user import User, UserRole
from app.schemas.yookassa import YooKassaPayment
from app.services import billing_service, yookassa_service
from app.services.auth_service import hash_password
from app.tasks import payment_pipeline

pytestmark = pytest.mark.integration

# 127.0.0.1 (the ASGI transport peer) is a trusted proxy, so the webhook reads
# the real client IP from X-Forwarded-For.
_TRUSTED_IP = "185.71.76.5"  # inside YOOKASSA_TRUSTED_CIDRS
_UNTRUSTED_IP = "8.8.8.8"
_TEST_CSRF = "test-csrf-fixed-value"


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


def _mock_get(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    *,
    amount: str = "190.00",
    currency: str = "RUB",
    paid: bool = True,
) -> None:
    async def _fake_get(yk_id: str) -> YooKassaPayment:
        data: dict[str, Any] = {"id": yk_id, "status": status}
        if status == "succeeded":
            data["paid"] = paid
            data["amount"] = {"value": amount, "currency": currency}
        return YooKassaPayment.model_validate(data)

    monkeypatch.setattr(yookassa_service, "get_payment", _fake_get)


def _mock_task(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Stop the eager Celery task from running and capture the enqueue call."""
    m = MagicMock(name="process_yookassa_payment.apply_async")
    monkeypatch.setattr(payment_pipeline.process_yookassa_payment, "apply_async", m)
    return m


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


async def _post_webhook(
    client: AsyncClient, body: dict, ip: str | None = _TRUSTED_IP
) -> Any:
    headers = {"X-Forwarded-For": ip} if ip else {}
    return await client.post(
        "/api/v1/billing/webhooks/yookassa", json=body, headers=headers
    )


# ── Create ──────────────────────────────────────────────────────────────────


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

    payment = await db_session.scalar(select(Payment).where(Payment.id == body["payment_id"]))
    assert payment is not None
    assert payment.status == PaymentStatus.pending
    assert payment.yookassa_payment_id == "yk-pay-1"
    assert payment.credits == CREDIT_PACKAGES["pack_50"]["credits"]
    assert float(payment.amount_rub) == CREDIT_PACKAGES["pack_50"]["price_rub"]
    # Idempotence-Key (≤64 chars) + per-payment return URL + metadata went to YooKassa.
    assert calls[0]["idempotence_key"] == payment.idempotence_key
    assert len(payment.idempotence_key) <= 64
    assert f"payment_id={payment.id}" in calls[0]["return_url"]
    assert calls[0]["metadata"]["payment_id"] == str(payment.id)
    assert calls[0]["metadata"]["user_id"] == str(teacher_user.id)


async def test_create_payment_unknown_package_400(
    client: AsyncClient, teacher_token: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/billing/payments",
        json={"package_key": "pack_999"},
        cookies=teacher_token,
    )
    assert resp.status_code == 400


async def test_create_payment_requires_verified_email(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.models.user import UserRole
    from app.services.auth_service import create_access_token, hash_password

    user = User(
        email=f"unverified-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("unverified-pass-123"),
        full_name="Unverified Teacher",
        role=UserRole.teacher,
        is_active=True,
        email_verified=False,
    )
    db_session.add(user)
    await db_session.commit()
    token, _jti, _exp = create_access_token(user)

    resp = await client.post(
        "/api/v1/billing/payments",
        json={"package_key": "pack_50"},
        cookies={"access_token": token, "csrf_token": _TEST_CSRF},
    )
    assert resp.status_code == 403


async def test_create_payment_ignores_client_price(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Price/credits come from the server catalogue; extra client fields are
    ignored, never trusted."""
    _mock_create(monkeypatch)
    resp = await client.post(
        "/api/v1/billing/payments",
        json={"package_key": "pack_50", "price_rub": 1, "amount_rub": "1.00", "credits": 99999},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    payment = await db_session.scalar(
        select(Payment).where(Payment.id == resp.json()["payment_id"])
    )
    assert payment.credits == CREDIT_PACKAGES["pack_50"]["credits"]
    assert float(payment.amount_rub) == CREDIT_PACKAGES["pack_50"]["price_rub"]


# ── Webhook (verify IP, enqueue, 200) ─────────────────────────────────────────


async def test_webhook_untrusted_ip_rejected(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _mock_task(monkeypatch)
    resp = await _post_webhook(
        client, {"event": "payment.succeeded", "object": {"id": "yk-pay-1"}}, ip=_UNTRUSTED_IP
    )
    assert resp.status_code == 400
    task.assert_not_called()


async def test_webhook_trusted_ip_enqueues_task(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _mock_task(monkeypatch)
    resp = await _post_webhook(client, {"event": "payment.succeeded", "object": {"id": "yk-pay-1"}})
    assert resp.status_code == 200
    task.assert_called_once()
    assert task.call_args.kwargs["args"] == ["payment.succeeded", "yk-pay-1"]


async def test_webhook_ignores_unknown_event(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _mock_task(monkeypatch)
    resp = await _post_webhook(client, {"event": "payment.created", "object": {"id": "yk-pay-1"}})
    assert resp.status_code == 200
    task.assert_not_called()


async def test_webhook_refund_uses_payment_id(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _mock_task(monkeypatch)
    resp = await _post_webhook(
        client,
        {"event": "refund.succeeded", "object": {"id": "refund-1", "payment_id": "yk-pay-1"}},
    )
    assert resp.status_code == 200
    task.assert_called_once()
    assert task.call_args.kwargs["args"] == ["refund.succeeded", "yk-pay-1"]


# ── Poll-path settlement (crediting / idempotency / validation) ───────────────


async def test_poll_endpoint_settles_pending_payment(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /payments/{id} pulls the authoritative status so local flows work
    without a publicly reachable webhook; crediting stays idempotent."""
    _mock_create(monkeypatch)
    body = await _create_payment(client, teacher_token)
    _mock_get(monkeypatch, "succeeded")  # amount 190.00 == pack_50 price

    resp = await client.get(
        f"/api/v1/billing/payments/{body['payment_id']}", cookies=teacher_token
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "succeeded"

    balance = await billing_service.get_balance(db_session, teacher_user.id)
    assert balance["balance"] == CREDIT_PACKAGES["pack_50"]["credits"]

    # Poll again — no double grant, exactly one PURCHASE ledger row.
    await client.get(f"/api/v1/billing/payments/{body['payment_id']}", cookies=teacher_token)
    balance2 = await billing_service.get_balance(db_session, teacher_user.id)
    assert balance2["balance"] == balance["balance"]

    history = await billing_service.get_transaction_history(db_session, teacher_user.id)
    purchases = [t for t in history if t.operation == CreditOperation.PURCHASE]
    assert len(purchases) == 1


async def test_poll_amount_mismatch_does_not_credit(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 'succeeded' payment whose authoritative amount differs from the package
    price must NOT grant credits — the payment stays pending."""
    _mock_create(monkeypatch)
    body = await _create_payment(client, teacher_token)  # pack_50 → 190.00
    _mock_get(monkeypatch, "succeeded", amount="1.00")

    resp = await client.get(
        f"/api/v1/billing/payments/{body['payment_id']}", cookies=teacher_token
    )
    assert resp.json()["status"] == "pending"
    balance = await billing_service.get_balance(db_session, teacher_user.id)
    assert balance["balance"] == 0


async def test_poll_does_not_credit_when_api_pending(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The authoritative API is the source of truth — a still-pending payment
    never credits, regardless of what any notification claimed."""
    _mock_create(monkeypatch)
    body = await _create_payment(client, teacher_token)
    _mock_get(monkeypatch, "pending")

    resp = await client.get(
        f"/api/v1/billing/payments/{body['payment_id']}", cookies=teacher_token
    )
    assert resp.json()["status"] == "pending"
    balance = await billing_service.get_balance(db_session, teacher_user.id)
    assert balance["balance"] == 0


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


async def test_webhook_exempt_from_cookie_auth_and_csrf(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Server-to-server: the webhook must accept a valid event from a trusted IP
    with NO access_token cookie and NO X-CSRF-Token (→ 200, not 401/403)."""
    task = _mock_task(monkeypatch)
    resp = await client.post(
        "/api/v1/billing/webhooks/yookassa",
        json={"event": "payment.succeeded", "object": {"id": "yk-pay-1"}},
        headers={"X-Forwarded-For": _TRUSTED_IP},
    )
    assert resp.status_code == 200
    task.assert_called_once()


# ── Reconcile sweep (sync task; psycopg2 session like the Celery worker) ───────


@pytest.fixture()
def sync_session(_alembic_upgraded: None) -> Iterator[Session]:
    """psycopg2 session mirroring the Celery worker; truncates after each test
    (the sync task holds its own connection, outside the async SAVEPOINT)."""
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    session_local = sessionmaker(bind=engine, expire_on_commit=False)
    sess = session_local()
    try:
        yield sess
    finally:
        sess.close()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE credit_transactions, credit_accounts, payments, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
            conn.commit()
        engine.dispose()


def _make_user_sync(sess: Session) -> User:
    user = User(
        email=f"recon-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("password123"),
        full_name="Recon Teacher",
        role=UserRole.teacher,
        is_active=True,
        email_verified=True,
    )
    sess.add(user)
    sess.commit()
    return user


def _make_pending_payment_sync(
    sess: Session, user: User, *, yk_id: str, package: str = "pack_50", age_minutes: int = 30
) -> Payment:
    pkg = CREDIT_PACKAGES[package]
    payment = Payment(
        user_id=user.id,
        package_key=package,
        amount_rub=pkg["price_rub"],
        credits=pkg["credits"],
        status=PaymentStatus.pending,
        idempotence_key=uuid.uuid4().hex,
        yookassa_payment_id=yk_id,
        created_at=datetime.now(timezone.utc) - timedelta(minutes=age_minutes),
    )
    sess.add(payment)
    sess.commit()
    return payment


def _mock_get_sync(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: str,
    payment_id: Any,
    amount: str = "190.00",
    currency: str = "RUB",
    paid: bool = True,
) -> None:
    def _fake(yk_id: str) -> YooKassaPayment:
        data: dict[str, Any] = {
            "id": yk_id,
            "status": status,
            "metadata": {"payment_id": str(payment_id)},
        }
        if status == "succeeded":
            data["paid"] = paid
            data["amount"] = {"value": amount, "currency": currency}
        return YooKassaPayment.model_validate(data)

    monkeypatch.setattr(yookassa_service, "get_payment_sync", _fake)


def _purchase_rows(sess: Session, user: User) -> list[CreditTransaction]:
    acct = sess.scalar(select(CreditAccount).where(CreditAccount.owner_id == user.id))
    if acct is None:
        return []
    return list(
        sess.scalars(
            select(CreditTransaction).where(
                CreditTransaction.account_id == acct.id,
                CreditTransaction.operation == CreditOperation.PURCHASE,
            )
        ).all()
    )


def test_reconcile_credits_stuck_succeeded_once(
    sync_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user_sync(sync_session)
    payment = _make_pending_payment_sync(sync_session, user, yk_id="yk-recon-1")
    _mock_get_sync(monkeypatch, status="succeeded", payment_id=payment.id)

    payment_pipeline.reconcile_pending_payments()

    sync_session.expire_all()
    refreshed = sync_session.get(Payment, payment.id)
    assert refreshed.status == PaymentStatus.succeeded
    assert refreshed.paid_at is not None
    purchases = _purchase_rows(sync_session, user)
    assert len(purchases) == 1
    assert purchases[0].delta == CREDIT_PACKAGES["pack_50"]["credits"]


def test_reconcile_and_webhook_task_credit_once(
    sync_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """reconcile + the webhook settle task on the same payment → credited once."""
    user = _make_user_sync(sync_session)
    payment = _make_pending_payment_sync(sync_session, user, yk_id="yk-recon-1")
    _mock_get_sync(monkeypatch, status="succeeded", payment_id=payment.id)

    payment_pipeline.reconcile_pending_payments()
    payment_pipeline.process_yookassa_payment("payment.succeeded", "yk-recon-1")

    sync_session.expire_all()
    purchases = _purchase_rows(sync_session, user)
    assert len(purchases) == 1
    acct = sync_session.scalar(select(CreditAccount).where(CreditAccount.owner_id == user.id))
    assert acct.balance == CREDIT_PACKAGES["pack_50"]["credits"]


def test_reconcile_marks_canceled(
    sync_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user_sync(sync_session)
    payment = _make_pending_payment_sync(sync_session, user, yk_id="yk-recon-1")
    _mock_get_sync(monkeypatch, status="canceled", payment_id=payment.id)

    payment_pipeline.reconcile_pending_payments()

    sync_session.expire_all()
    assert sync_session.get(Payment, payment.id).status == PaymentStatus.canceled
    assert _purchase_rows(sync_session, user) == []


def test_reconcile_amount_mismatch_does_not_credit(
    sync_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user_sync(sync_session)
    payment = _make_pending_payment_sync(sync_session, user, yk_id="yk-recon-1")
    _mock_get_sync(monkeypatch, status="succeeded", payment_id=payment.id, amount="1.00")

    payment_pipeline.reconcile_pending_payments()

    sync_session.expire_all()
    assert sync_session.get(Payment, payment.id).status == PaymentStatus.pending
    assert _purchase_rows(sync_session, user) == []


def test_reconcile_skips_too_recent(
    sync_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Younger than RECONCILE_MIN_AGE_MINUTES → not even fetched."""
    user = _make_user_sync(sync_session)
    payment = _make_pending_payment_sync(sync_session, user, yk_id="yk-recon-1", age_minutes=1)
    calls = {"n": 0}

    def _fake(yk_id: str) -> YooKassaPayment:
        calls["n"] += 1
        return YooKassaPayment.model_validate(
            {
                "id": yk_id,
                "status": "succeeded",
                "paid": True,
                "amount": {"value": "190.00", "currency": "RUB"},
                "metadata": {"payment_id": str(payment.id)},
            }
        )

    monkeypatch.setattr(yookassa_service, "get_payment_sync", _fake)

    payment_pipeline.reconcile_pending_payments()

    assert calls["n"] == 0
    sync_session.expire_all()
    assert sync_session.get(Payment, payment.id).status == PaymentStatus.pending


def test_reconcile_alerts_stuck_once(
    sync_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = _make_user_sync(sync_session)
    payment = _make_pending_payment_sync(sync_session, user, yk_id="yk-recon-1", age_minutes=120)
    # Still pending at YooKassa → reconcile can't resolve it → alert.
    _mock_get_sync(monkeypatch, status="pending", payment_id=payment.id)

    payment_pipeline.reconcile_pending_payments()
    sync_session.expire_all()
    refreshed = sync_session.get(Payment, payment.id)
    assert refreshed.status == PaymentStatus.pending
    assert refreshed.alerted_at is not None
    first_alert = refreshed.alerted_at

    # Second sweep must NOT re-alert (alerted_at already set).
    payment_pipeline.reconcile_pending_payments()
    sync_session.expire_all()
    assert sync_session.get(Payment, payment.id).alerted_at == first_alert
