"""Unit tests for the delivery decisions: presence gate, dedup, digest collapse.

The DB is stubbed out (a one-method fake session) so these stay pure decision
tests — the routing rules, not SQLAlchemy.
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import fakeredis
import pytest

from app.constants import NOTIFY_DIGEST_MAX_ITEMS, NOTIFY_PRESENCE_TTL_SECONDS
from app.models.user import User
from app.services import notification_service as ns

pytestmark = pytest.mark.unit


def _redis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


def _user(**overrides: Any) -> User:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "email": "t@example.com",
        "full_name": "Иван",
        "is_active": True,
        "email_verified": True,
        "deleted_at": None,
        "notify_content": True,
        "notify_feedback": True,
        "notify_submissions": True,
    }
    defaults.update(overrides)
    return User(**defaults)


class _FakeSession:
    """Stands in for SyncSession() — `get` is the only call the task makes."""

    def __init__(self, user: User | None) -> None:
        self._user = user

    def get(self, _model: type, _pk: Any) -> User | None:
        return self._user

    def close(self) -> None:
        return None


@pytest.fixture()
def wired(monkeypatch: pytest.MonkeyPatch):
    """Point the task at a fake Redis and let each test choose the user row."""
    import app.tasks.notification_pipeline as np

    redis = _redis()
    monkeypatch.setattr(np, "_get_sync_redis", lambda: redis)
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(np, "send_email_sync", lambda **kw: sent.append(kw))

    def _use(user: User | None) -> None:
        monkeypatch.setattr(np, "SyncSession", lambda: _FakeSession(user))

    _use(_user())
    return type("Wired", (), {"np": np, "redis": redis, "sent": sent, "use": staticmethod(_use)})


def _payload(**extra: Any) -> dict[str, Any]:
    base = {"entity_id": "e1", "lesson_id": "l1", "lesson_title": "Урок", "url": "/x"}
    base.update(extra)
    return base


# ── Recipient / preference gate ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "overrides",
    [
        {"is_active": False},
        {"email_verified": False},
        {"email": None},
    ],
)
def test_skips_undeliverable_recipient(wired: Any, overrides: dict[str, Any]) -> None:
    wired.use(_user(**overrides))
    result = wired.np.decide_and_deliver(
        str(uuid.uuid4()), ns.NotificationEvent.comment_posted.value, _payload()
    )
    assert result["status"] == "skipped_recipient"
    assert wired.sent == []


def test_skips_missing_user(wired: Any) -> None:
    wired.use(None)
    result = wired.np.decide_and_deliver(
        str(uuid.uuid4()), ns.NotificationEvent.comment_posted.value, _payload()
    )
    assert result["status"] == "skipped_recipient"


def test_skips_disabled_category(wired: Any) -> None:
    wired.use(_user(notify_feedback=False))
    result = wired.np.decide_and_deliver(
        str(uuid.uuid4()), ns.NotificationEvent.comment_posted.value, _payload()
    )
    assert result["status"] == "skipped_unsubscribed"
    assert wired.sent == []


def test_other_categories_still_deliver_when_one_is_off(wired: Any) -> None:
    wired.use(_user(notify_feedback=False))
    result = wired.np.decide_and_deliver(
        str(uuid.uuid4()), ns.NotificationEvent.lesson_ready.value, _payload()
    )
    assert result["status"] == "queued_digest"


def test_unknown_event_is_dropped(wired: Any) -> None:
    assert wired.np.decide_and_deliver(str(uuid.uuid4()), "not_an_event", {})["status"] == (
        "unknown_event"
    )


# ── Presence gate ────────────────────────────────────────────────────────────


def test_lesson_ready_dropped_while_stream_is_open(wired: Any) -> None:
    wired.redis.zadd(ns.presence_key("l1"), {"conn-a": time.time()})
    result = wired.np.decide_and_deliver(
        str(uuid.uuid4()), ns.NotificationEvent.lesson_ready.value, _payload()
    )
    # Dropped outright, not deferred: the digest would be the same noise later.
    assert result["status"] == "skipped_present"


def test_second_tab_keeps_presence_after_first_closes(wired: Any) -> None:
    key = ns.presence_key("l1")
    wired.redis.zadd(key, {"tab-a": time.time(), "tab-b": time.time()})
    wired.redis.zrem(key, "tab-a")
    result = wired.np.decide_and_deliver(
        str(uuid.uuid4()), ns.NotificationEvent.lesson_ready.value, _payload()
    )
    assert result["status"] == "skipped_present"


def test_stale_presence_entry_does_not_suppress(wired: Any) -> None:
    """A connection dropped without a clean close must age out."""
    stale = time.time() - NOTIFY_PRESENCE_TTL_SECONDS - 10
    wired.redis.zadd(ns.presence_key("l1"), {"dead-conn": stale})
    result = wired.np.decide_and_deliver(
        str(uuid.uuid4()), ns.NotificationEvent.lesson_ready.value, _payload()
    )
    assert result["status"] == "queued_digest"


def test_presence_does_not_gate_other_events(wired: Any) -> None:
    wired.redis.zadd(ns.presence_key("l1"), {"conn-a": time.time()})
    result = wired.np.decide_and_deliver(
        str(uuid.uuid4()), ns.NotificationEvent.comment_posted.value, _payload()
    )
    assert result["status"] == "sent"


# ── Dedup ────────────────────────────────────────────────────────────────────


def test_repeat_inside_window_is_not_resent(wired: Any) -> None:
    user_id = str(uuid.uuid4())
    first = wired.np.decide_and_deliver(
        user_id, ns.NotificationEvent.comment_posted.value, _payload()
    )
    second = wired.np.decide_and_deliver(
        user_id, ns.NotificationEvent.comment_posted.value, _payload()
    )
    assert first["status"] == "sent"
    assert second["status"] == "skipped_duplicate"
    assert len(wired.sent) == 1


def test_dedup_is_scoped_per_entity(wired: Any) -> None:
    user_id = str(uuid.uuid4())
    wired.np.decide_and_deliver(
        user_id, ns.NotificationEvent.comment_posted.value, _payload(entity_id="a")
    )
    result = wired.np.decide_and_deliver(
        user_id, ns.NotificationEvent.comment_posted.value, _payload(entity_id="b")
    )
    assert result["status"] == "sent"
    assert len(wired.sent) == 2


def test_dedup_not_marked_when_send_fails(wired: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A provider failure must stay retriable — the dedup key is set only after
    the send succeeded."""
    from app.services.email_service import EmailDeliveryError

    def _fail(**_kw: object) -> None:
        raise EmailDeliveryError("provider 5xx")

    monkeypatch.setattr(wired.np, "send_email_sync", _fail)
    user_id = str(uuid.uuid4())
    with pytest.raises(EmailDeliveryError):
        wired.np.decide_and_deliver(user_id, ns.NotificationEvent.comment_posted.value, _payload())
    assert not wired.redis.exists(ns.dedup_key(user_id, ns.NotificationEvent.comment_posted, "e1"))


def test_urgent_mail_carries_list_unsubscribe_headers(wired: Any) -> None:
    wired.np.decide_and_deliver(
        str(uuid.uuid4()), ns.NotificationEvent.comment_posted.value, _payload()
    )
    headers = wired.sent[0]["headers"]
    assert headers["List-Unsubscribe"].startswith("<http")
    assert headers["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


# ── Digest accumulation + flush ──────────────────────────────────────────────


def test_ten_lessons_collapse_into_one_digest(wired: Any) -> None:
    user_id = str(uuid.uuid4())
    for i in range(10):
        wired.np.decide_and_deliver(
            user_id,
            ns.NotificationEvent.lesson_ready.value,
            _payload(entity_id=f"lesson-{i}", lesson_id=f"lesson-{i}"),
        )
    assert wired.sent == []  # nothing goes out immediately

    items, total = wired.np._pop_digest(wired.redis, user_id)
    assert len(items) == 10
    assert total == 10

    mails: list[dict[str, Any]] = []
    session = _FakeSession(_user())
    wired.np.send_email.delay = lambda **kw: mails.append(kw)  # type: ignore[method-assign]
    assert wired.np._flush_one(session, user_id, items, total) == 1
    assert len(mails) == 1
    assert len(mails[0]["context"]["items"]) == 10


def test_digest_overflow_is_collapsed(wired: Any) -> None:
    user_id = str(uuid.uuid4())
    overflow_by = 5
    for i in range(NOTIFY_DIGEST_MAX_ITEMS + overflow_by):
        wired.np._push_digest(
            wired.redis, user_id, {"category": "notify_content", "title": f"t{i}", "url": None}
        )
    items, total = wired.np._pop_digest(wired.redis, user_id)
    assert len(items) == NOTIFY_DIGEST_MAX_ITEMS
    assert total == NOTIFY_DIGEST_MAX_ITEMS + overflow_by

    mails: list[dict[str, Any]] = []
    wired.np.send_email.delay = lambda **kw: mails.append(kw)  # type: ignore[method-assign]
    wired.np._flush_one(_FakeSession(_user()), user_id, items, total)
    assert mails[0]["context"]["overflow"] == overflow_by


def test_pop_is_the_idempotency_token(wired: Any) -> None:
    """A replayed flush finds an empty accumulator and mails nothing."""
    user_id = str(uuid.uuid4())
    wired.np._push_digest(wired.redis, user_id, {"category": "notify_content", "title": "t"})
    assert wired.np._pop_digest(wired.redis, user_id)[0]
    assert wired.np._pop_digest(wired.redis, user_id) == ([], 0)


def test_flush_skips_user_deactivated_after_the_event(wired: Any) -> None:
    mails: list[dict[str, Any]] = []
    wired.np.send_email.delay = lambda **kw: mails.append(kw)  # type: ignore[method-assign]
    items = [{"category": "notify_content", "title": "t", "url": None}]
    session = _FakeSession(_user(is_active=False))
    assert wired.np._flush_one(session, str(uuid.uuid4()), items, 1) == 0
    assert mails == []


def test_flush_honours_an_unsubscribe_made_after_accumulation(wired: Any) -> None:
    mails: list[dict[str, Any]] = []
    wired.np.send_email.delay = lambda **kw: mails.append(kw)  # type: ignore[method-assign]
    items = [{"category": "notify_content", "title": "t", "url": None}]
    session = _FakeSession(_user(notify_content=False))
    assert wired.np._flush_one(session, str(uuid.uuid4()), items, 1) == 0
    assert mails == []


def test_empty_accumulator_sends_nothing(wired: Any) -> None:
    mails: list[dict[str, Any]] = []
    wired.np.send_email.delay = lambda **kw: mails.append(kw)  # type: ignore[method-assign]
    assert wired.np.flush_notification_digests() == {"users": 0, "emails": 0}
    assert mails == []


def test_redis_outage_does_not_raise(wired: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Every Redis touch is best-effort; an outage degrades, never explodes."""

    class _DeadRedis:
        def __getattr__(self, _name: str):
            def _boom(*_a: object, **_kw: object) -> None:
                raise ConnectionError("redis down")

            return _boom

    monkeypatch.setattr(wired.np, "_get_sync_redis", _DeadRedis)
    # urgent still goes out (dedup read fails open), digest degrades to a no-op
    assert (
        wired.np.decide_and_deliver(
            str(uuid.uuid4()), ns.NotificationEvent.comment_posted.value, _payload()
        )["status"]
        == "sent"
    )
    assert (
        wired.np.decide_and_deliver(
            str(uuid.uuid4()), ns.NotificationEvent.lesson_ready.value, _payload()
        )["status"]
        == "digest_unavailable"
    )
    assert wired.np.flush_notification_digests() == {"users": 0, "emails": 0}


# ── Dedup scope at the call sites ────────────────────────────────────────────


def test_lesson_ready_dedups_per_generation_not_per_lesson(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: entity_id used to be the lesson id, so a regeneration inside
    the 6h window was swallowed as a duplicate. The Celery task id is stable
    across an acks_late replay but fresh on every new run — the right scope."""
    import app.tasks.video_pipeline as vp
    from app.models.lesson import Lesson

    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(ns, "notify", lambda _uid, _ev, payload: captured.append(payload))

    lesson = Lesson(id=uuid.uuid4(), title="Интегралы")
    vp._enqueue_video_ready_email(lesson, uuid.uuid4(), "task-abc")

    assert captured[0]["entity_id"] == "task-abc"
    # lesson_id stays in the payload — the presence gate keys off it.
    assert captured[0]["lesson_id"] == str(lesson.id)


def test_quiz_generated_dedups_per_generation(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.tasks.quiz_pipeline as qp

    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(qp, "notify", lambda _uid, _ev, payload: captured.append(payload))

    lesson_id = uuid.uuid4()
    qp._notify_quiz_ready(_FakeSession(None), lesson_id, uuid.uuid4(), "task-xyz")

    assert captured[0]["entity_id"] == "task-xyz"
    assert captured[0]["lesson_id"] == str(lesson_id)
