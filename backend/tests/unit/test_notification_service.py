"""Unit tests for the notification event registry and the unsubscribe token."""

from __future__ import annotations

import uuid

import pytest

from app.models.user import User
from app.services import notification_service as ns

pytestmark = pytest.mark.unit


def test_every_event_has_a_spec() -> None:
    assert set(ns.REGISTRY) == set(ns.NotificationEvent)


def test_every_category_is_a_real_user_column() -> None:
    """The category enum *value* is the User column name — the settings API, the
    registry and the unsubscribe link all rely on that identity."""
    columns = {c.name for c in User.__table__.columns}
    for category in ns.NotificationCategory:
        assert category.value in columns


def test_urgent_and_digest_split_matches_product_rules() -> None:
    urgent = {e for e, s in ns.REGISTRY.items() if s.kind is ns.DeliveryKind.urgent}
    digest = {e for e, s in ns.REGISTRY.items() if s.kind is ns.DeliveryKind.digest}
    assert urgent == {
        ns.NotificationEvent.comment_posted,
        ns.NotificationEvent.grade_posted,
        ns.NotificationEvent.assignment_message,
    }
    assert digest == {
        ns.NotificationEvent.lesson_ready,
        ns.NotificationEvent.quiz_generated,
        ns.NotificationEvent.submission_received,
    }


def test_only_lesson_ready_is_presence_gated() -> None:
    gated = {e for e, s in ns.REGISTRY.items() if s.presence_gated}
    assert gated == {ns.NotificationEvent.lesson_ready}


def test_render_title_interpolates_payload() -> None:
    title = ns.render_title(ns.NotificationEvent.lesson_ready, {"lesson_title": "Интегралы"})
    assert title == "Видеолекция «Интегралы» готова"


def test_render_title_survives_missing_key() -> None:
    """A payload that lost a key must not lose the whole notification."""
    title = ns.render_title(ns.NotificationEvent.lesson_ready, {})
    assert title == ns.REGISTRY[ns.NotificationEvent.lesson_ready].title


# ── Unsubscribe token ────────────────────────────────────────────────────────


def test_unsubscribe_token_roundtrip() -> None:
    user_id = str(uuid.uuid4())
    token = ns.generate_unsubscribe_token(user_id, ns.NotificationCategory.feedback)
    assert ns.verify_unsubscribe_token(token) == (user_id, ns.NotificationCategory.feedback)


def test_unsubscribe_token_rejects_tampering() -> None:
    token = ns.generate_unsubscribe_token(str(uuid.uuid4()), ns.NotificationCategory.content)
    with pytest.raises(ValueError, match="invalid"):
        ns.verify_unsubscribe_token(token[:-1] + ("A" if token[-1] != "A" else "B"))


def test_unsubscribe_token_rejects_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    token = ns.generate_unsubscribe_token(str(uuid.uuid4()), ns.NotificationCategory.content)
    monkeypatch.setattr(ns, "NOTIFY_UNSUBSCRIBE_TTL_SECONDS", -1)
    with pytest.raises(ValueError, match="expired"):
        ns.verify_unsubscribe_token(token)


def test_unsubscribe_token_rejects_unknown_category() -> None:
    """A correctly signed token can still only name a category that exists —
    it must never be able to flip an arbitrary column."""
    forged = ns._unsubscribe_serializer().dumps({"uid": str(uuid.uuid4()), "cat": "is_active"})
    with pytest.raises(ValueError, match="invalid"):
        ns.verify_unsubscribe_token(forged)


def test_unsubscribe_token_rejects_non_uuid_owner() -> None:
    forged = ns._unsubscribe_serializer().dumps({"uid": "not-a-uuid", "cat": "notify_content"})
    with pytest.raises(ValueError, match="invalid"):
        ns.verify_unsubscribe_token(forged)


def test_notify_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """A broker outage degrades to a log line — it must not surface in the
    request or pipeline that triggered the notification."""
    import app.tasks.notification_pipeline as np

    def _boom(**_kwargs: object) -> None:
        raise ConnectionError("broker down")

    monkeypatch.setattr(np.deliver_notification, "delay", _boom)
    ns.notify(uuid.uuid4(), ns.NotificationEvent.lesson_ready, {"entity_id": "x"})
