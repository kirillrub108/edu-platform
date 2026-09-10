"""Resend delivery webhook: signature, dedup, and what each event type does.

The route only verifies the signature and enqueues; Celery is EAGER here, so the
sync task runs in-process on its OWN psycopg2 connection. That connection cannot
see rows created on the test's SAVEPOINT-bound async session, so every fixture
row and every assertion in this file goes through `sync_session`.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any, Iterator

import fakeredis
import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

import app.config as app_config
from app.models.email_suppression import EmailSuppression, SuppressionReason
from app.models.user import User, UserRole
from app.services.auth_service import hash_password

pytestmark = pytest.mark.integration

_SECRET = "whsec_" + base64.b64encode(b"resend-test-signing-key-0123456789").decode()


@pytest.fixture()
def sync_session(_alembic_upgraded: None) -> Iterator[Session]:
    """psycopg2 session mirroring the Celery worker; truncates after each test."""
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    session_local = sessionmaker(bind=engine, expire_on_commit=False)
    sess = session_local()
    try:
        yield sess
    finally:
        sess.close()
        with engine.connect() as conn:
            conn.execute(text("TRUNCATE TABLE email_suppressions, users RESTART IDENTITY CASCADE"))
            conn.commit()
        engine.dispose()


@pytest.fixture(autouse=True)
def webhook_env(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Configure the signing secret and give the task a private fake Redis, so
    the svix-id dedup set does not leak between tests.

    `app_config.settings` is resolved here, not imported at module scope: the
    session fixture in conftest rebuilds the singleton after the testcontainer
    URL is known, so a module-level binding would patch a stale object.
    """
    from app.tasks import email_pipeline

    monkeypatch.setattr(app_config.settings, "RESEND_WEBHOOK_SECRET", _SECRET)
    fake = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(email_pipeline, "_get_sync_redis", lambda: fake)
    return fake


def _sign(body: bytes, svix_id: str, ts: int | None = None) -> dict[str, str]:
    ts = ts if ts is not None else int(time.time())
    key = base64.b64decode(_SECRET.removeprefix("whsec_"))
    signed = f"{svix_id}.{ts}.".encode() + body
    sig = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    return {
        "svix-id": svix_id,
        "svix-timestamp": str(ts),
        "svix-signature": f"v1,{sig}",
    }


def _bounce_payload(email: str, *, bounce_type: str = "hard") -> dict[str, Any]:
    return {
        "type": "email.bounced",
        "created_at": "2026-09-10T03:00:00.000Z",
        "data": {
            "email_id": f"msg-{uuid.uuid4().hex[:8]}",
            "to": [email],
            "bounce": {"type": bounce_type, "message": "550 mailbox unavailable"},
        },
    }


async def _post(client: AsyncClient, payload: dict[str, Any], svix_id: str) -> Any:
    body = json.dumps(payload).encode()
    return await client.post("/api/v1/webhooks/resend", content=body, headers=_sign(body, svix_id))


def _make_user_sync(sess: Session, email: str) -> User:
    user = User(
        email=email,
        hashed_password=hash_password("password123"),
        full_name="Bounce Teacher",
        role=UserRole.teacher,
        is_active=True,
        email_verified=True,
    )
    sess.add(user)
    sess.commit()
    return user


def _suppression(sess: Session, email: str) -> EmailSuppression | None:
    sess.expire_all()
    return sess.scalar(select(EmailSuppression).where(EmailSuppression.email == email))


# ── Signature ────────────────────────────────────────────────────────────────


async def test_hard_bounce_suppresses_and_flags_user(
    client: AsyncClient, sync_session: Session
) -> None:
    user = _make_user_sync(sync_session, "dead@nowhere.invalid")

    resp = await _post(client, _bounce_payload("dead@nowhere.invalid"), "msg_1")

    assert resp.status_code == 200
    row = _suppression(sync_session, "dead@nowhere.invalid")
    assert row is not None
    assert row.reason is SuppressionReason.hard_bounce
    assert row.hits == 1

    sync_session.expire_all()
    refreshed = sync_session.get(User, user.id)
    assert refreshed.email_bounced_at is not None
    assert refreshed.email_bounce_reason == "hard_bounce"


async def test_bad_signature_is_rejected_and_writes_nothing(
    client: AsyncClient, sync_session: Session
) -> None:
    payload = _bounce_payload("nope@nowhere.invalid")
    body = json.dumps(payload).encode()
    headers = _sign(body, "msg_bad")
    headers["svix-signature"] = "v1," + base64.b64encode(b"wrong-signature-bytes").decode()

    resp = await client.post("/api/v1/webhooks/resend", content=body, headers=headers)

    assert resp.status_code == 400
    assert _suppression(sync_session, "nope@nowhere.invalid") is None


async def test_stale_timestamp_is_rejected(client: AsyncClient, sync_session: Session) -> None:
    """A correctly signed but hours-old request is a replay, not a delivery."""
    payload = _bounce_payload("stale@nowhere.invalid")
    body = json.dumps(payload).encode()
    headers = _sign(body, "msg_stale", ts=int(time.time()) - 7200)

    resp = await client.post("/api/v1/webhooks/resend", content=body, headers=headers)

    assert resp.status_code == 400
    assert _suppression(sync_session, "stale@nowhere.invalid") is None


async def test_unconfigured_secret_returns_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_config.settings, "RESEND_WEBHOOK_SECRET", "")
    resp = await client.post("/api/v1/webhooks/resend", content=b"{}")
    assert resp.status_code == 503


# ── Idempotency ──────────────────────────────────────────────────────────────


async def test_same_event_redelivered_changes_nothing(
    client: AsyncClient, sync_session: Session
) -> None:
    """Resend retries on any hiccup. The same svix-id must be a full no-op —
    not a second hit on a single real bounce."""
    payload = _bounce_payload("retry@nowhere.invalid")
    body = json.dumps(payload).encode()
    headers = _sign(body, "msg_same")

    first = await client.post("/api/v1/webhooks/resend", content=body, headers=headers)
    assert first.status_code == 200
    before = _suppression(sync_session, "retry@nowhere.invalid")
    assert before is not None
    hits_before, occurred_before = before.hits, before.occurred_at

    second = await client.post("/api/v1/webhooks/resend", content=body, headers=headers)
    assert second.status_code == 200

    after = _suppression(sync_session, "retry@nowhere.invalid")
    assert after is not None
    assert after.hits == hits_before == 1
    assert after.occurred_at == occurred_before


async def test_second_independent_bounce_increments_hits(
    client: AsyncClient, sync_session: Session
) -> None:
    """A genuinely new event for the same address bumps the counter instead of
    inserting a duplicate row."""
    assert (await _post(client, _bounce_payload("twice@nowhere.invalid"), "msg_a")).status_code
    assert (await _post(client, _bounce_payload("twice@nowhere.invalid"), "msg_b")).status_code

    sync_session.expire_all()
    rows = sync_session.scalars(
        select(EmailSuppression).where(EmailSuppression.email == "twice@nowhere.invalid")
    ).all()
    assert len(rows) == 1
    assert rows[0].hits == 2


# ── Event types ──────────────────────────────────────────────────────────────


async def test_soft_bounce_does_not_suppress(client: AsyncClient, sync_session: Session) -> None:
    resp = await _post(
        client, _bounce_payload("full@nowhere.invalid", bounce_type="soft"), "msg_soft"
    )
    assert resp.status_code == 200
    assert _suppression(sync_session, "full@nowhere.invalid") is None


async def test_complaint_suppresses(client: AsyncClient, sync_session: Session) -> None:
    payload = {
        "type": "email.complained",
        "data": {"email_id": "msg-c1", "to": ["angry@example.com"]},
    }
    resp = await _post(client, payload, "msg_complaint")

    assert resp.status_code == 200
    row = _suppression(sync_session, "angry@example.com")
    assert row is not None
    assert row.reason is SuppressionReason.complaint


async def test_delivered_clears_bounce_for_current_address(
    client: AsyncClient, sync_session: Session
) -> None:
    user = _make_user_sync(sync_session, "recovered@example.com")
    await _post(client, _bounce_payload("recovered@example.com"), "msg_b1")

    payload = {
        "type": "email.delivered",
        "data": {"email_id": "msg-d1", "to": ["recovered@example.com"]},
    }
    resp = await _post(client, payload, "msg_d1")

    assert resp.status_code == 200
    assert _suppression(sync_session, "recovered@example.com") is None
    sync_session.expire_all()
    refreshed = sync_session.get(User, user.id)
    assert refreshed.email_bounced_at is None
    assert refreshed.email_bounce_reason is None


async def test_delivered_does_not_lift_a_complaint(
    client: AsyncClient, sync_session: Session
) -> None:
    """Providers can deliver events out of order; someone who pressed "spam"
    must not be put back on the send list by a late delivered."""
    await _post(
        client,
        {"type": "email.complained", "data": {"email_id": "m1", "to": ["angry2@example.com"]}},
        "msg_c2",
    )
    await _post(
        client,
        {"type": "email.delivered", "data": {"email_id": "m2", "to": ["angry2@example.com"]}},
        "msg_d2",
    )

    row = _suppression(sync_session, "angry2@example.com")
    assert row is not None
    assert row.reason is SuppressionReason.complaint


async def test_event_for_unknown_address_still_suppresses(
    client: AsyncClient, sync_session: Session
) -> None:
    """No account holds this address (never registered, or already purged). The
    suppression row is still the useful part; nothing raises."""
    resp = await _post(client, _bounce_payload("ghost@nowhere.invalid"), "msg_ghost")

    assert resp.status_code == 200
    assert _suppression(sync_session, "ghost@nowhere.invalid") is not None


async def test_unknown_event_type_is_accepted_and_ignored(
    client: AsyncClient, sync_session: Session
) -> None:
    payload = {
        "type": "email.opened",
        "data": {"email_id": "msg-o1", "to": ["curious@example.com"]},
    }
    resp = await _post(client, payload, "msg_open")

    assert resp.status_code == 200
    assert _suppression(sync_session, "curious@example.com") is None


async def test_address_case_is_normalized(client: AsyncClient, sync_session: Session) -> None:
    user = _make_user_sync(sync_session, "mixed@example.com")
    resp = await _post(client, _bounce_payload("Mixed@Example.COM"), "msg_case")

    assert resp.status_code == 200
    assert _suppression(sync_session, "mixed@example.com") is not None
    sync_session.expire_all()
    assert sync_session.get(User, user.id).email_bounced_at is not None
