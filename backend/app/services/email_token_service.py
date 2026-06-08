"""One-time email-verification tokens + resend cooldown, backed by Redis.

The token itself stays the stateless signed value minted by `auth_service`
(itsdangerous, no DB row). This module layers two Redis-backed guarantees on
top, reusing the project's shared async Redis client:

  * one-time use — a successfully consumed token's fingerprint is recorded at
    ``email_verify_used:<sha256(token)>`` (TTL = token lifetime). A second
    consume of the same token raises ``TokenError("used")``. The signed token
    payload is left untouched so the existing stateless GET path and its tests
    keep working.
  * resend cooldown — ``email_verify_cooldown:<user_id>`` (TTL =
    ``EMAIL_VERIFY_RESEND_COOLDOWN_SECONDS``) throttles resend per-user,
    independent of the slowapi per-IP limit.
"""

from __future__ import annotations

import hashlib

from redis.asyncio import Redis

from app.constants import (
    EMAIL_VERIFICATION_TTL_SECONDS,
    EMAIL_VERIFY_RESEND_COOLDOWN_SECONDS,
)
from app.services.auth_service import (
    generate_email_verification_token,
    verify_email_verification_token,
)


class TokenError(ValueError):
    """A verification token could not be consumed. ``reason`` is a stable code
    ('invalid' | 'expired' | 'used') suitable for use directly as an API detail
    or redirect reason."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _used_key(token: str) -> str:
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"email_verify_used:{digest}"


def _cooldown_key(user_id: str) -> str:
    return f"email_verify_cooldown:{user_id}"


def issue(user_id: str) -> str:
    """Mint a fresh verification token for ``user_id``."""
    return generate_email_verification_token(user_id)


async def consume(redis: Redis, token: str) -> str:
    """Validate ``token`` and atomically burn it, returning the user_id.

    Raises ``TokenError('invalid' | 'expired')`` for a tampered/expired token
    and ``TokenError('used')`` if the same token was already consumed.
    """
    try:
        user_id = verify_email_verification_token(token)
    except ValueError as exc:
        raise TokenError(str(exc)) from exc

    # SET NX is atomic: the first caller wins and marks the token spent; any
    # concurrent or later replay of the same token gets a falsey result.
    fresh = await redis.set(
        _used_key(token), user_id, nx=True, ex=EMAIL_VERIFICATION_TTL_SECONDS
    )
    if not fresh:
        raise TokenError("used")
    return user_id


async def under_cooldown(redis: Redis, user_id: str) -> bool:
    return bool(await redis.exists(_cooldown_key(user_id)))


async def start_cooldown(redis: Redis, user_id: str) -> None:
    await redis.set(
        _cooldown_key(user_id), "1", ex=EMAIL_VERIFY_RESEND_COOLDOWN_SECONDS
    )
