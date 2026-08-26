"""Single entry point for *product* notification email.

`notify(user_id, event, payload)` is the only public call site API. It does no
IO beyond enqueuing `deliver_notification` on the `celery_email` queue, so the
same function is safe from async routers and from sync Celery tasks alike —
there is no async/sync twin to keep in step.

Everything else (settings lookup, dedup, urgent-vs-digest, presence gate,
render, send) lives in `app/tasks/notification_pipeline.py`.

Auth mail — email verification and password reset — deliberately does NOT pass
through here: it is transactional and must go out regardless of any preference.

This module also owns the pieces both halves of the subsystem must agree on:
the event registry, the Redis key layout (async SSE route writes presence, the
sync task reads it), and the signed unsubscribe token.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Final
from uuid import UUID

import structlog
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.config import settings
from app.constants import NOTIFY_UNSUBSCRIBE_TTL_SECONDS

logger = structlog.get_logger()


class NotificationCategory(str, Enum):
    """A user-facing preference group. The value is the `User` column name, so
    the registry, the settings API and the unsubscribe link all agree without a
    second mapping table."""

    content = "notify_content"
    feedback = "notify_feedback"
    submissions = "notify_submissions"


class NotificationEvent(str, Enum):
    lesson_ready = "lesson_ready"
    quiz_generated = "quiz_generated"
    submission_received = "submission_received"
    comment_posted = "comment_posted"
    grade_posted = "grade_posted"
    assignment_message = "assignment_message"


class DeliveryKind(str, Enum):
    urgent = "urgent"
    digest = "digest"


@dataclass(frozen=True)
class EventSpec:
    kind: DeliveryKind
    category: NotificationCategory
    subject: str
    #: str.format template over the payload; renders both the single-event mail
    #: body line and the digest row.
    title: str
    #: Gate the mail on an open SSE stream for `payload["lesson_id"]`: if the
    #: user is watching the result appear, the event is dropped outright.
    presence_gated: bool = False


REGISTRY: Final[dict[NotificationEvent, EventSpec]] = {
    NotificationEvent.lesson_ready: EventSpec(
        kind=DeliveryKind.digest,
        category=NotificationCategory.content,
        subject="Видеолекция готова — Edllm",
        title="Видеолекция «{lesson_title}» готова",
        presence_gated=True,
    ),
    NotificationEvent.quiz_generated: EventSpec(
        kind=DeliveryKind.digest,
        category=NotificationCategory.content,
        subject="Тест сгенерирован — Edllm",
        title="Тест к уроку «{lesson_title}» сгенерирован",
    ),
    NotificationEvent.submission_received: EventSpec(
        kind=DeliveryKind.digest,
        category=NotificationCategory.submissions,
        subject="Новая сдача работы — Edllm",
        title="{student_name} сдал(а) работу «{assignment_title}»",
    ),
    NotificationEvent.comment_posted: EventSpec(
        kind=DeliveryKind.urgent,
        category=NotificationCategory.feedback,
        subject="Новый комментарий преподавателя — Edllm",
        title="Преподаватель оставил комментарий к уроку «{lesson_title}»",
    ),
    NotificationEvent.grade_posted: EventSpec(
        kind=DeliveryKind.urgent,
        category=NotificationCategory.feedback,
        subject="Работа проверена — Edllm",
        title="Работа «{assignment_title}» проверена: {points} из {max_points}",
    ),
    NotificationEvent.assignment_message: EventSpec(
        kind=DeliveryKind.urgent,
        category=NotificationCategory.feedback,
        subject="Новое сообщение по работе — Edllm",
        title="Новое сообщение в обсуждении работы «{assignment_title}»",
    ),
}


def render_title(event: NotificationEvent, payload: dict[str, Any]) -> str:
    """Fill the registry title from `payload`. A missing/renamed key degrades to
    the raw template rather than losing the notification."""
    spec = REGISTRY[event]
    try:
        return spec.title.format(**payload)
    except (KeyError, IndexError):
        logger.warning("notification_title_render_failed", event_type=event.value)
        return spec.title


# ── Redis key layout (shared by the async SSE route and the sync task) ───────


def dedup_key(user_id: str, event: NotificationEvent, entity_id: str) -> str:
    return f"notify:sent:{user_id}:{event.value}:{entity_id}"


def digest_key(user_id: str) -> str:
    return f"notify:digest:{user_id}"


DIGEST_KEY_PATTERN: Final[str] = "notify:digest:*"


def presence_key(lesson_id: str) -> str:
    """Sorted set of live SSE connections for one lesson: member = connection id,
    score = last heartbeat. A set (not a flag) so two tabs are two members and
    closing one doesn't clear presence for the other, while a connection dropped
    without a clean close simply ages out of the score window."""
    return f"notify:presence:lesson:{lesson_id}"


# ── Signed unsubscribe token ─────────────────────────────────────────────────
# Same itsdangerous scheme as email verification (auth_service), isolated by its
# own salt. The token carries a user id and one category and nothing else, so it
# can only ever switch off one notification category for its own owner.

_UNSUBSCRIBE_SALT: Final[str] = "notify-unsubscribe"


def _unsubscribe_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt=_UNSUBSCRIBE_SALT)


def generate_unsubscribe_token(user_id: str, category: NotificationCategory) -> str:
    return _unsubscribe_serializer().dumps({"uid": user_id, "cat": category.value})


def verify_unsubscribe_token(token: str) -> tuple[str, NotificationCategory]:
    """Return `(user_id, category)`. Raises ValueError('expired' | 'invalid') —
    never a 5xx — so the public endpoint can redirect with a reason code."""
    try:
        data = _unsubscribe_serializer().loads(token, max_age=NOTIFY_UNSUBSCRIBE_TTL_SECONDS)
    except SignatureExpired as exc:
        raise ValueError("expired") from exc
    except BadSignature as exc:
        raise ValueError("invalid") from exc
    if not isinstance(data, dict):
        raise ValueError("invalid")
    try:
        category = NotificationCategory(data["cat"])
        user_id = str(data["uid"])
        UUID(user_id)
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid") from exc
    return user_id, category


def unsubscribe_url(user_id: str, category: NotificationCategory) -> str:
    token = generate_unsubscribe_token(user_id, category)
    return f"{settings.BASE_URL}/api/v1/notifications/unsubscribe?token={token}"


# ── Public API ───────────────────────────────────────────────────────────────


def notify(user_id: str | UUID, event: NotificationEvent, payload: dict[str, Any]) -> None:
    """Enqueue one product notification. Never raises: a broker outage degrades
    to a log line instead of failing the request or pipeline that triggered it.

    `payload` must carry `entity_id` (dedup scope) and may carry `url` plus any
    keys the registry title interpolates.
    """
    try:
        from app.tasks.notification_pipeline import deliver_notification

        deliver_notification.delay(
            user_id=str(user_id),
            event=event.value,
            payload=payload,
        )
    except Exception:
        logger.warning(
            "notification_enqueue_failed",
            user_id=str(user_id),
            event_type=event.value,
            exc_info=True,
        )
