"""Delivery half of the notification subsystem (see services/notification_service).

Two tasks:

* ``deliver_notification`` (queue ``celery_email``) — decides and delivers one
  event: preference check → presence gate → dedup → send now (urgent) or append
  to the user's digest accumulator (digest).
* ``flush_notification_digests`` (queue ``quiz``, driven by the single beat) —
  drains the accumulators and mails one grouped digest per user per category.

Sync-only, like every task module: psycopg2 ``SyncSession`` and a sync Redis
client, never an AsyncSession.

Redis is treated as best-effort throughout. The presence and dedup reads fail
*open* (deliver rather than swallow) so an outage degrades to "possibly a
duplicate", never to "silently lost". Nothing here is allowed to raise into the
caller — ``notify()`` already returned long before this runs.
"""

from __future__ import annotations

import json
import time
from typing import Any
from uuid import UUID

import redis as _sync_redis
import structlog
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.constants import (
    EMAIL_SEND_MAX_RETRIES,
    EMAIL_SEND_RETRY_BACKOFF,
    NOTIFY_DEDUP_TTL_SECONDS,
    NOTIFY_DIGEST_FLUSH_BATCH,
    NOTIFY_DIGEST_MAX_ITEMS,
    NOTIFY_DIGEST_TTL_SECONDS,
    NOTIFY_PRESENCE_TTL_SECONDS,
)
from app.models.user import User
from app.services.email_service import EmailDeliveryError, send_email_sync
from app.services.notification_service import (
    DIGEST_KEY_PATTERN,
    REGISTRY,
    DeliveryKind,
    NotificationCategory,
    NotificationEvent,
    dedup_key,
    digest_key,
    presence_key,
    render_title,
    unsubscribe_url,
)
from app.tasks.email_pipeline import send_email
from app.tasks.video_pipeline import SyncSession, _get_sync_redis

logger = structlog.get_logger()

_DIGEST_COUNT_PREFIX = "notify:digestn:"


def _digest_count_key(user_id: str) -> str:
    """Total pushed count, kept beside the (capped) item list so the flush can
    say "и ещё N" for what the cap dropped. Separate prefix so the accumulator
    SCAN pattern doesn't match it."""
    return f"{_DIGEST_COUNT_PREFIX}{user_id}"


def _unsubscribe_headers(url: str) -> dict[str, str]:
    """RFC 2369 + RFC 8058 one-click unsubscribe. The POST target is the same
    endpoint the human-clickable link uses."""
    return {
        "List-Unsubscribe": f"<{url}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


def _deliverable(user: User | None) -> bool:
    """A notification is only mailed to a live, active, verified mailbox. An
    unverified user is skipped outright — they never proved they own the
    address, and product mail is not the place to spam it."""
    return bool(
        user is not None
        and user.deleted_at is None
        and user.is_active
        and user.email_verified
        and user.email
    )


def _is_watching(r: "_sync_redis.Redis", lesson_id: str) -> bool:
    """True while at least one live SSE stream for this lesson is present.

    Stale members (a connection dropped without a clean close) are swept by
    score first, so a browser crash cannot suppress notifications forever.
    Fails open — an unreachable Redis reads as "not watching", i.e. the mail
    still goes out.
    """
    key = presence_key(lesson_id)
    try:
        r.zremrangebyscore(key, "-inf", time.time() - NOTIFY_PRESENCE_TTL_SECONDS)
        return bool(r.zcard(key))
    except Exception:
        logger.warning("notification_presence_check_failed", lesson_id=lesson_id, exc_info=True)
        return False


def _already_sent(r: "_sync_redis.Redis", key: str) -> bool:
    try:
        return bool(r.exists(key))
    except Exception:
        logger.warning("notification_dedup_check_failed", exc_info=True)
        return False


def _mark_sent(r: "_sync_redis.Redis", key: str) -> None:
    try:
        r.set(key, "1", ex=NOTIFY_DEDUP_TTL_SECONDS)
    except Exception:
        logger.warning("notification_dedup_mark_failed", exc_info=True)


def _push_digest(r: "_sync_redis.Redis", user_id: str, item: dict[str, Any]) -> bool:
    """Append one item to the user's accumulator, capped at NOTIFY_DIGEST_MAX_ITEMS.
    The counter keeps growing past the cap so the flush can report the overflow."""
    items_key, count_key = digest_key(user_id), _digest_count_key(user_id)
    try:
        pipe = r.pipeline()
        pipe.rpush(items_key, json.dumps(item, ensure_ascii=False))
        pipe.ltrim(items_key, 0, NOTIFY_DIGEST_MAX_ITEMS - 1)
        pipe.incr(count_key)
        pipe.expire(items_key, NOTIFY_DIGEST_TTL_SECONDS)
        pipe.expire(count_key, NOTIFY_DIGEST_TTL_SECONDS)
        pipe.execute()
        return True
    except Exception:
        logger.warning("notification_digest_push_failed", user_id=user_id, exc_info=True)
        return False


def _pop_digest(r: "_sync_redis.Redis", user_id: str) -> tuple[list[dict[str, Any]], int]:
    """Atomically drain the accumulator, returning (items, total_pushed).

    The pop *is* the idempotency token for the flush: if the worker dies after
    this and the task is replayed under acks_late, the replay finds an empty
    accumulator and mails nothing.
    """
    items_key, count_key = digest_key(user_id), _digest_count_key(user_id)
    pipe = r.pipeline()
    pipe.lrange(items_key, 0, -1)
    pipe.get(count_key)
    pipe.delete(items_key)
    pipe.delete(count_key)
    raw, total, _, _ = pipe.execute()

    items: list[dict[str, Any]] = []
    for entry in raw or []:
        try:
            items.append(json.loads(entry))
        except json.JSONDecodeError:
            logger.warning("notification_digest_item_corrupt", user_id=user_id)
    return items, int(total or len(items))


@celery_app.task(
    bind=True,
    name="deliver_notification",
    queue="celery_email",
    autoretry_for=(EmailDeliveryError,),
    retry_backoff=EMAIL_SEND_RETRY_BACKOFF,
    retry_kwargs={"max_retries": EMAIL_SEND_MAX_RETRIES},
    acks_late=True,
)
def deliver_notification(self, user_id: str, event: str, payload: dict[str, Any]) -> dict:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(task_id=self.request.id, task_name=self.name)
    return decide_and_deliver(user_id, event, payload)


def decide_and_deliver(user_id: str, event: str, payload: dict[str, Any]) -> dict:
    """The task body, callable directly from tests. Returns a status dict whose
    `status` names the branch taken."""
    try:
        event_enum = NotificationEvent(event)
    except ValueError:
        logger.warning("notification_unknown_event", event_type=event)
        return {"status": "unknown_event"}

    spec = REGISTRY[event_enum]
    session: Session = SyncSession()
    try:
        user = session.get(User, UUID(user_id))
        if not _deliverable(user):
            return {"status": "skipped_recipient"}
        assert user is not None  # narrowed by _deliverable
        if not getattr(user, spec.category.value):
            return {"status": "skipped_unsubscribed"}
        recipient, full_name = user.email, user.full_name or ""
    finally:
        session.close()

    r = _get_sync_redis()

    lesson_id = payload.get("lesson_id")
    if spec.presence_gated and lesson_id and _is_watching(r, str(lesson_id)):
        # The user is looking at the result appear on screen — mailing them
        # about it is noise, and deferring it to the digest is the same noise
        # 30 minutes later. Drop it entirely.
        return {"status": "skipped_present"}

    key = dedup_key(user_id, event_enum, str(payload.get("entity_id", "")))
    if _already_sent(r, key):
        return {"status": "skipped_duplicate"}

    title = render_title(event_enum, payload)
    url = payload.get("url")

    if spec.kind is DeliveryKind.digest:
        pushed = _push_digest(
            r, user_id, {"category": spec.category.value, "title": title, "url": url}
        )
        if not pushed:
            return {"status": "digest_unavailable"}
        _mark_sent(r, key)
        return {"status": "queued_digest"}

    unsub = unsubscribe_url(user_id, spec.category)
    send_email_sync(
        to=recipient,
        subject=spec.subject,
        template_name="notification.html",
        context={
            "full_name": full_name,
            "title": title,
            "url": url,
            "unsubscribe_url": unsub,
        },
        headers=_unsubscribe_headers(unsub),
    )
    # Only after the provider accepted it — a failed send must stay retriable.
    _mark_sent(r, key)
    return {"status": "sent"}


def _plural_events(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return "событие"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return "события"
    return "событий"


def _flush_one(session: Session, user_id: str, items: list[dict[str, Any]], total: int) -> int:
    """Mail one digest per category present in `items`. Returns mails enqueued."""
    user = session.get(User, UUID(user_id))
    if not _deliverable(user):
        # Deactivated / deleted between the event and the flush — the items were
        # already popped, so they simply disappear.
        return 0
    assert user is not None

    overflow = max(0, total - len(items))
    sent = 0
    for category in NotificationCategory:
        grouped = [i for i in items if i.get("category") == category.value]
        if not grouped or not getattr(user, category.value):
            # Unsubscribed after the item was accumulated — honour the newer choice.
            continue
        # The cap dropped items we can no longer attribute to a category; report
        # the overflow on whichever digest goes out, rather than losing the count.
        extra = overflow if sent == 0 else 0
        unsub = unsubscribe_url(user_id, category)
        count = len(grouped) + extra
        send_email.delay(
            to=user.email,
            subject=f"Edllm: {count} {_plural_events(count)}",
            template_name="notification_digest.html",
            context={
                "full_name": user.full_name or "",
                "heading": f"{count} {_plural_events(count)} за последнее время",
                "items": grouped,
                "overflow": extra,
                "unsubscribe_url": unsub,
            },
            headers=_unsubscribe_headers(unsub),
        )
        sent += 1
    return sent


@celery_app.task(name="flush_notification_digests", queue="quiz")
def flush_notification_digests() -> dict:
    """Beat job: drain every non-empty digest accumulator into one mail per user
    per category. An empty accumulator sends nothing."""
    structlog.contextvars.clear_contextvars()
    r = _get_sync_redis()
    try:
        keys = []
        for key in r.scan_iter(match=DIGEST_KEY_PATTERN, count=100):
            keys.append(key)
            if len(keys) >= NOTIFY_DIGEST_FLUSH_BATCH:
                break
    except Exception:
        logger.warning("notification_digest_scan_failed", exc_info=True)
        return {"users": 0, "emails": 0}

    users = emails = 0
    session: Session = SyncSession()
    try:
        for key in keys:
            user_id = str(key).rsplit(":", 1)[-1]
            try:
                items, total = _pop_digest(r, user_id)
            except Exception:
                logger.warning("notification_digest_pop_failed", user_id=user_id, exc_info=True)
                continue
            if not items:
                continue
            users += 1
            emails += _flush_one(session, user_id, items, total)
    finally:
        session.close()

    logger.info("notification_digests_flushed", users=users, emails=emails)
    return {"users": users, "emails": emails}
