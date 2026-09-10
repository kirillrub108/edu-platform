"""Unit tests for the parts of the suppression path that touch no database:
address normalization, the svix-id replay guard, and the send_email drop.

The DB-backed half (record_event / sync_clear_for_email) is exercised end to end
through the webhook in tests/integration/test_email_webhooks.py.
"""

from __future__ import annotations

from typing import Any

import fakeredis
import pytest

from app.services import email_suppression_service as sup

pytestmark = pytest.mark.unit


@pytest.fixture()
def fake_redis() -> Any:
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Bob@Example.COM", "bob@example.com"),
        ("  spaced@example.com  ", "spaced@example.com"),
        ("already@lower.ru", "already@lower.ru"),
    ],
)
def test_normalize_lowercases_and_strips(raw: str, expected: str) -> None:
    assert sup.normalize(raw) == expected


def test_seen_event_is_false_once_then_true(fake_redis: Any) -> None:
    """First sighting proceeds; every redelivery of the same svix-id is a no-op."""
    assert sup.seen_event(fake_redis, "msg_abc") is False
    assert sup.seen_event(fake_redis, "msg_abc") is True
    assert sup.seen_event(fake_redis, "msg_abc") is True


def test_seen_event_is_per_event_id(fake_redis: Any) -> None:
    assert sup.seen_event(fake_redis, "msg_1") is False
    assert sup.seen_event(fake_redis, "msg_2") is False


def test_send_email_skips_suppressed_address_without_retrying(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A suppressed address must not reach the provider, and must not raise —
    raising EmailDeliveryError would buy three more sends to a dead mailbox."""
    from app.tasks import email_pipeline

    sent: list[dict[str, Any]] = []

    class _NullSession:
        def __enter__(self) -> "_NullSession":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(email_pipeline, "SyncSession", _NullSession)
    monkeypatch.setattr(
        email_pipeline.email_suppression_service, "sync_is_suppressed", lambda _db, _to: True
    )
    monkeypatch.setattr(email_pipeline, "send_email_sync", lambda **kw: sent.append(kw))

    result = email_pipeline.send_email.apply(
        kwargs={
            "to": "dead@example.com",
            "subject": "Подтвердите ваш email",
            "template_name": "verify_email.html",
            "context": {},
        }
    ).get()

    assert result == {"status": "suppressed", "to": "dead@example.com"}
    assert sent == []


def test_send_email_sends_when_not_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import email_pipeline

    sent: list[dict[str, Any]] = []

    class _NullSession:
        def __enter__(self) -> "_NullSession":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

    monkeypatch.setattr(email_pipeline, "SyncSession", _NullSession)
    monkeypatch.setattr(
        email_pipeline.email_suppression_service, "sync_is_suppressed", lambda _db, _to: False
    )
    monkeypatch.setattr(email_pipeline, "send_email_sync", lambda **kw: sent.append(kw))

    result = email_pipeline.send_email.apply(
        kwargs={
            "to": "alive@example.com",
            "subject": "Подтвердите ваш email",
            "template_name": "verify_email.html",
            "context": {},
        }
    ).get()

    assert result == {"status": "sent", "to": "alive@example.com"}
    assert len(sent) == 1
    assert sent[0]["to"] == "alive@example.com"
