"""One-time, DB-backed password-reset tokens.

Unlike the stateless email-verification token (`email_token_service`), a reset
token must be revocable with certainty, so it is persisted — but only as a
SHA-256 hash. The raw value exists solely inside the emailed link, never in the
DB, so a database leak cannot be turned into a password reset. `issue` mints a
fresh token row; `consume` validates and burns it in one shot, raising
`TokenError` with a stable reason the caller collapses into a single opaque
failure (so it never reveals whether a token was unknown, expired, or spent).

Both functions mutate the session but do NOT commit — the caller owns the
transaction so the burn and the password change land atomically.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import PASSWORD_RESET_TOKEN_BYTES, PASSWORD_RESET_TTL_SECONDS
from app.models.password_reset_token import PasswordResetToken


class TokenError(ValueError):
    """A reset token could not be consumed. `reason` is a stable internal code
    ('invalid' | 'expired' | 'used') — for logging only; the endpoint maps every
    reason to one opaque client error so token state never leaks."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def issue(db: AsyncSession, user_id: str) -> str:
    """Mint a reset token for `user_id`, persist its hash, and return the raw
    token (the only place the raw value ever exists). Caller commits."""
    raw = secrets.token_urlsafe(PASSWORD_RESET_TOKEN_BYTES)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=PASSWORD_RESET_TTL_SECONDS)
    db.add(
        PasswordResetToken(
            user_id=UUID(user_id),
            token_hash=_hash(raw),
            expires_at=expires_at,
        )
    )
    return raw


async def consume(db: AsyncSession, raw: str) -> str:
    """Validate `raw` and burn it (mark used), returning the owning user_id.

    Raises `TokenError('invalid' | 'expired' | 'used')`. The row's `used_at` is
    set here but not committed — the caller commits it together with the new
    password hash so the token cannot be reused even if the request later fails.
    """
    row = await db.scalar(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == _hash(raw))
    )
    if row is None:
        raise TokenError("invalid")
    if row.used_at is not None:
        raise TokenError("used")
    if row.expires_at <= datetime.now(timezone.utc):
        raise TokenError("expired")
    row.used_at = datetime.now(timezone.utc)
    return str(row.user_id)
