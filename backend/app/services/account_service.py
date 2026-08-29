"""Account lifecycle: self-deletion, the restore window, early email release,
and the anonymization that replaces physical deletion at purge time.

The shape of it (DECISIONS §59):

    delete ──► soft-deleted, email still OCCUPIED, restorable for
               SOFT_DELETE_PURGE_DAYS
                 ├─ restore (token from mail, or email+password) ──► active again
                 ├─ confirm-release (token from mail) ────────────► anonymized now
                 └─ window elapses ──► purge_soft_deleted anonymizes or deletes

`anonymize_user_fields` is the single definition of "what a tombstoned user
looks like", and it is deliberately pure: the async path here and the sync
Celery purge task both call it, and neither can share a session with the other.
File removal sits next to each call site rather than inside it.

Both mailed links are stateless `itsdangerous` tokens with their own salts, the
same mechanism as email verification and unsubscribe — no new table.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import structlog
from fastapi import HTTPException, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    ACCOUNT_RESTORE_PATH,
    ACCOUNT_RESTORE_TTL_SECONDS,
    ANONYMIZED_EMAIL_DOMAIN,
    EMAIL_RELEASE_PATH,
    EMAIL_RELEASE_TTL_SECONDS,
    PROFILE_DELETED_USER_NAME,
    SOFT_DELETE_PURGE_DAYS,
)
from app.models.course import Course
from app.models.lesson import Lesson, LessonStatus, Module
from app.models.user import User
from app.services import profile_service
from app.services.auth_service import AuthService, soft_delete_user, verify_password

logger = structlog.get_logger()

_RESTORE_SALT = "account-restore"
_RELEASE_SALT = "email-release"

# Argon2 never produces this, so it can never verify — and unlike a random hash
# it is self-describing when someone reads the row.
_UNUSABLE_PASSWORD_HASH = "!anonymized"

_LESSONS_IN_FLIGHT = (LessonStatus.analyzing, LessonStatus.processing)


# ── Tombstone (pure) ─────────────────────────────────────────────────────────


def anonymize_user_fields(user: User) -> None:
    """Strip every piece of personal data from a user row, in place.

    Pure by design — no session, no I/O — because the sync purge task and the
    async release path must both apply exactly this definition. `deleted_at` is
    kept: the row stays soft-deleted forever, it is simply no longer personal.

    The tombstone address is derived from the id (not random) so it is stable
    across re-runs, and lives under a reserved .invalid domain so it can never
    collide with a real sign-up.
    """
    user.email = f"deleted+{user.id}@{ANONYMIZED_EMAIL_DOMAIN}"
    user.full_name = PROFILE_DELETED_USER_NAME
    user.bio = None
    user.avatar_image_path = None
    user.avatar_external_url = None
    user.hashed_password = _UNUSABLE_PASSWORD_HASH
    user.pdn_consent_at = None
    user.terms_accepted_at = None
    user.marketing_consent = False
    user.marketing_consent_at = None
    user.consent_policy_version = None
    user.consent_ip = None
    user.is_active = False


def is_anonymized(user: User) -> bool:
    """Idempotence check for the purge task — re-anonymizing daily would churn
    the row and the log for no reason."""
    return (user.email or "").endswith(f"@{ANONYMIZED_EMAIL_DOMAIN}")


def restore_deadline(user: User) -> datetime | None:
    if user.deleted_at is None:
        return None
    deleted_at = user.deleted_at
    if deleted_at.tzinfo is None:
        deleted_at = deleted_at.replace(tzinfo=timezone.utc)
    return deleted_at + timedelta(days=SOFT_DELETE_PURGE_DAYS)


def within_restore_window(user: User) -> bool:
    deadline = restore_deadline(user)
    return deadline is not None and datetime.now(timezone.utc) < deadline


# ── Signed links ─────────────────────────────────────────────────────────────


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt=salt)


def generate_restore_token(user_id: str) -> str:
    return _serializer(_RESTORE_SALT).dumps(user_id)


def verify_restore_token(token: str) -> str:
    """user_id from a valid restore token. Raises ValueError on anything else —
    callers collapse every failure into one opaque 400."""
    try:
        return _serializer(_RESTORE_SALT).loads(token, max_age=ACCOUNT_RESTORE_TTL_SECONDS)
    except SignatureExpired:
        raise ValueError("expired")
    except BadSignature:
        raise ValueError("invalid")


def generate_release_token(user_id: str) -> str:
    return _serializer(_RELEASE_SALT).dumps(user_id)


def verify_release_token(token: str) -> str:
    try:
        return _serializer(_RELEASE_SALT).loads(token, max_age=EMAIL_RELEASE_TTL_SECONDS)
    except SignatureExpired:
        raise ValueError("expired")
    except BadSignature:
        raise ValueError("invalid")


def _release_used_key(token: str) -> str:
    return f"email_release_used:{hashlib.sha256(token.encode()).hexdigest()}"


async def burn_release_token(redis: Redis, token: str) -> bool:
    """Atomically mark a release token spent. False = already used.

    The token itself is stateless and immutable, so single use has to be tracked
    somewhere; SET NX is the same burn email verification uses.
    """
    marked = await redis.set(_release_used_key(token), "1", nx=True, ex=EMAIL_RELEASE_TTL_SECONDS)
    return bool(marked)


def restore_url(token: str) -> str:
    return f"{settings.FRONTEND_URL}{ACCOUNT_RESTORE_PATH}?token={token}"


def release_url(token: str) -> str:
    return f"{settings.FRONTEND_URL}{EMAIL_RELEASE_PATH}?token={token}"


# ── Lookups that must see through the soft-delete filter ─────────────────────


async def get_user_including_deleted(db: AsyncSession, user_id: UUID) -> User | None:
    return await db.scalar(
        select(User).where(User.id == user_id).execution_options(include_deleted=True)
    )


async def get_pending_deletion_by_email(db: AsyncSession, email: str) -> User | None:
    """A soft-deleted account still holding `email`, if any.

    Case-insensitive on both sides for the same reason oauth_service is:
    pre-existing rows may hold a mixed-case address (KNOWN_PROBLEMS).
    """
    return await db.scalar(
        select(User)
        .where(func.lower(User.email) == email.strip().lower(), User.deleted_at.isnot(None))
        .execution_options(include_deleted=True)
    )


# ── Deletion ─────────────────────────────────────────────────────────────────


async def _has_lessons_in_flight(db: AsyncSession, user: User) -> bool:
    found = await db.scalar(
        select(Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .where(Course.owner_id == user.id, Lesson.status.in_(_LESSONS_IN_FLIGHT))
        .limit(1)
    )
    return found is not None


def clear_auth_cookies(response: Response) -> None:
    """Mirror of routers/auth._clear_auth_cookies for the deletion route, which
    builds its own 204 Response."""
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/v1/auth/refresh")
    response.delete_cookie("csrf_token", path="/")


async def delete_own_account(
    db: AsyncSession,
    service: AuthService,
    *,
    user: User,
    password: str,
    access_payload: dict,
) -> None:
    """Soft-delete the caller's account and revoke every session.

    Idempotent: a second call on an already-deleted row is a no-op (in practice
    unreachable, since the first call invalidates the cookie).
    """
    if user.deleted_at is not None:
        return
    if not user.hashed_password or not verify_password(password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Неверный текущий пароль"
        )
    # Generation in flight: the Celery task would keep writing to a row we are
    # about to hide, and the reserved credits are still owed back.
    if await _has_lessons_in_flight(db, user):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="lessons_in_progress",
        )

    email = user.email
    full_name = user.full_name
    soft_delete_user(user)
    await db.commit()

    await service.logout_all_sessions(str(user.id))
    jti = access_payload.get("jti")
    exp = access_payload.get("exp")
    if jti and exp:
        # The `exp` claim is an epoch int; logout() blacklists until a datetime.
        await service.logout(
            jti,
            datetime.fromtimestamp(int(exp), tz=timezone.utc),
            user_id=str(user.id),
            family_id=access_payload.get("family_id"),
        )

    _enqueue_deletion_email(user, email=email, full_name=full_name)
    logger.info("account_soft_deleted", user_id=str(user.id))


def _enqueue_deletion_email(user: User, *, email: str, full_name: str | None) -> None:
    """Deletion confirmation carrying the restore link. Auth mail goes straight
    to the queue (like verification and reset), not through notification_service
    — this is not a product notification and no preference may suppress it."""
    from app.tasks.email_pipeline import send_email

    deadline = restore_deadline(user)
    try:
        send_email.delay(
            to=email,
            subject="Аккаунт удалён — Edllm",
            template_name="account_deleted.html",
            context={
                "full_name": full_name or "",
                "restore_url": restore_url(generate_restore_token(str(user.id))),
                "restore_until": deadline.strftime("%d.%m.%Y") if deadline else "",
            },
        )
    except Exception:
        logger.warning("account_deleted_email_enqueue_failed", user_id=str(user.id), exc_info=True)


# ── Restore ──────────────────────────────────────────────────────────────────


_OPAQUE_RESTORE_ERROR = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_or_expired"
)


async def restore_account(
    db: AsyncSession,
    *,
    token: str | None,
    email: str | None,
    password: str | None,
) -> User:
    """Undo a soft delete via the mailed token or the original credentials.

    Every failure — bad token, wrong password, unknown address, elapsed window,
    already-anonymized row — collapses into one opaque 400. Distinguishing them
    would turn this into an account-enumeration oracle.
    """
    user: User | None = None
    if token:
        try:
            user_id = verify_restore_token(token)
        except ValueError:
            raise _OPAQUE_RESTORE_ERROR
        try:
            user = await get_user_including_deleted(db, UUID(user_id))
        except ValueError:
            raise _OPAQUE_RESTORE_ERROR
    elif email and password:
        user = await get_pending_deletion_by_email(db, email)
        if user is not None and (
            not user.hashed_password or not verify_password(password, user.hashed_password)
        ):
            raise _OPAQUE_RESTORE_ERROR
    else:
        raise _OPAQUE_RESTORE_ERROR

    if user is None or user.deleted_at is None or is_anonymized(user):
        raise _OPAQUE_RESTORE_ERROR
    if not within_restore_window(user):
        raise _OPAQUE_RESTORE_ERROR

    user.deleted_at = None
    user.is_active = True
    await db.commit()
    logger.info("account_restored", user_id=str(user.id))
    return user


# ── Early email release ──────────────────────────────────────────────────────


async def request_email_release(db: AsyncSession, email: str) -> None:
    """Mail the "free this address" link if the address really is held by an
    account inside its restore window. Silent otherwise — the route answers 204
    either way, so this must not signal anything by raising."""
    user = await get_pending_deletion_by_email(db, email)
    if user is None or is_anonymized(user) or not within_restore_window(user):
        return

    from app.tasks.email_pipeline import send_email

    try:
        send_email.delay(
            to=user.email,
            subject="Освобождение адреса — Edllm",
            template_name="email_release.html",
            context={
                "full_name": user.full_name or "",
                "release_url": release_url(generate_release_token(str(user.id))),
            },
        )
    except Exception:
        logger.warning("email_release_enqueue_failed", user_id=str(user.id), exc_info=True)


async def confirm_email_release(db: AsyncSession, redis: Redis, token: str) -> None:
    """Burn the token, anonymize immediately, free the address.

    Restoring afterwards is impossible by construction: the password hash and
    the email are gone, so neither restore path can ever match this row again.
    """
    try:
        user_id = verify_release_token(token)
    except ValueError:
        raise _OPAQUE_RESTORE_ERROR
    if not await burn_release_token(redis, token):
        raise _OPAQUE_RESTORE_ERROR
    try:
        user = await get_user_including_deleted(db, UUID(user_id))
    except ValueError:
        raise _OPAQUE_RESTORE_ERROR
    # deleted_at is re-checked here, not only at mail time: the owner may have
    # restored the account in the meantime, and a live account must never be
    # anonymized by a link that predates the restore.
    if user is None or user.deleted_at is None:
        raise _OPAQUE_RESTORE_ERROR
    if is_anonymized(user):
        return

    anonymize_user_fields(user)
    profile_service.drop_avatar_file(user.id)
    await db.commit()
    logger.info("account_anonymized_on_release", user_id=str(user.id))
