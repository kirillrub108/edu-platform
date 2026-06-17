"""Authentication service: password hashing, JWT issue/decode, and the
session/token-rotation logic backed by Redis.

Token model
-----------
Login mints a fresh "family" — a uuid4 grouping the rotating refresh tokens
that share a single absolute lifetime. The currently-valid jti for the family
is stored at `refresh:{user_id}:{family_id}`. Every refresh:

  * looks up the family record;
  * rejects the call (and burns the family) if the presented jti is not the
    one we stored — that's a reuse signal, the original token was stolen;
  * re-checks the absolute deadline (sliding window can't extend past it);
  * mints a new pair, overwriting the family record with the new jti and
    resetting the sliding TTL.

Logout blacklists the access jti until its natural exp and deletes the
refresh family identified by the `family_id` claim carried in the access
token (the refresh cookie is path-scoped and never reaches /auth/logout).
Logout-all wipes every
`refresh:{user_id}:*` key — already-issued access tokens stay valid until
they expire on their own (≤ ACCESS_TOKEN_EXPIRE_MINUTES) which is the
trade-off we accept to keep the access path stateless.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, HTTPException, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import EMAIL_VERIFICATION_TTL_SECONDS
from app.database import get_db
from app.models.user import User, UserRole
from app.redis_client import get_redis
from app.schemas.auth import TokenResponse

# ── Password hashing (argon2id — OWASP-recommended defaults from argon2-cffi).
# Memory-hard, no 72-byte input limit, no pre-hash hacks.

_ph = PasswordHasher()


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False


def soft_delete_user(user: User) -> None:
    """Soft-delete a user in place: mark deleted, deactivate (so existing tokens
    fail get_current_user's is_active check → 401), and anonymize PII. The row
    is physically removed later by the purge_soft_deleted task. Caller commits."""
    user.deleted_at = datetime.now(timezone.utc)
    user.is_active = False
    user.email = f"deleted_{uuid.uuid4().hex}@anon.invalid"
    user.full_name = None


# ── JWT primitives ───────────────────────────────────────────────────────────


def _encode(payload: dict[str, Any]) -> str:
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(user: User, family_id: str | None = None) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at). `family_id` ties the access token to
    its refresh family so logout can revoke that family from the access cookie
    alone (the refresh cookie is path-scoped and never reaches /auth/logout)."""
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    jti = str(uuid.uuid4())
    payload = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role.value,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "type": "access",
    }
    if family_id is not None:
        payload["family_id"] = family_id
    return _encode(payload), jti, exp


def create_refresh_token(
    user_id: str,
    family_id: str,
    *,
    sliding_days: int,
    absolute_expires_at: datetime,
) -> tuple[str, str, datetime]:
    """Returns (token, jti, expires_at). The JWT exp is min(sliding, absolute)
    so the token can never outlive the family's absolute deadline even if the
    Redis layer is bypassed."""
    now = datetime.now(timezone.utc)
    sliding_exp = now + timedelta(days=sliding_days)
    exp = min(sliding_exp, absolute_expires_at)
    jti = str(uuid.uuid4())
    payload = {
        "sub": user_id,
        "family_id": family_id,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "type": "refresh",
    }
    return _encode(payload), jti, exp


def decode_token(token: str, *, verify_exp: bool = True) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": verify_exp},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


# ── Stateless email-verification token (itsdangerous, signed with SECRET_KEY) ──
# No DB row — the token *is* the proof. A separate salt isolates it from any
# other itsdangerous use of the same SECRET_KEY.

_EMAIL_VERIFY_SALT = "email-verify"


def _email_verify_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.SECRET_KEY, salt=_EMAIL_VERIFY_SALT)


def generate_email_verification_token(user_id: str) -> str:
    return _email_verify_serializer().dumps(user_id)


def verify_email_verification_token(token: str) -> str:
    """Return the user_id carried by a valid token. Raises ValueError (never an
    HTTP 5xx) on an expired or tampered token so callers can redirect cleanly.
    The ValueError message ('expired' | 'invalid') doubles as the redirect
    reason code."""
    try:
        return _email_verify_serializer().loads(token, max_age=EMAIL_VERIFICATION_TTL_SECONDS)
    except SignatureExpired as exc:
        raise ValueError("expired") from exc
    except BadSignature as exc:
        raise ValueError("invalid") from exc


# ── Service ──────────────────────────────────────────────────────────────────


class AuthService:
    def __init__(self, db: AsyncSession, redis: Redis) -> None:
        self.db = db
        self.redis = redis

    @staticmethod
    def _family_key(user_id: str, family_id: str) -> str:
        return f"refresh:{user_id}:{family_id}"

    @staticmethod
    def _blacklist_key(jti: str) -> str:
        return f"blacklist:{jti}"

    # ── registration / login ────────────────────────────────────────────────

    async def register(
        self,
        email: str,
        password: str,
        full_name: str | None,
        role: UserRole = UserRole.teacher,
    ) -> User:
        existing = await self.db.scalar(select(User).where(User.email == email))
        if existing:
            raise HTTPException(status_code=409, detail="Email already registered")

        user = User(
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            role=role,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def login(self, email: str, password: str, remember_me: bool = True) -> TokenResponse:
        user = await self.db.scalar(select(User).where(User.email == email))
        if not user or not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if not user.is_active:
            raise HTTPException(status_code=403, detail="User is inactive")
        return await self.issue_session(user, remember_me=remember_me)

    async def issue_session(self, user: User, *, remember_me: bool = True) -> TokenResponse:
        """Start a fresh refresh family and mint the first access/refresh pair
        for it. The credential check is the caller's responsibility — used by
        login and by change_password (to re-establish the current session after
        every family was wiped)."""
        family_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        absolute_expires_at = now + timedelta(days=settings.REFRESH_TOKEN_ABSOLUTE_MAX_DAYS)
        sliding_days = (
            settings.REFRESH_TOKEN_EXPIRE_DAYS
            if remember_me
            else settings.REFRESH_TOKEN_SESSION_DAYS  # noqa: E501
        )
        return await self._mint_pair(
            user=user,
            family_id=family_id,
            created_at=now,
            absolute_expires_at=absolute_expires_at,
            sliding_days=sliding_days,
        )

    # ── refresh / rotation ──────────────────────────────────────────────────

    async def refresh(self, refresh_token: str) -> TokenResponse:
        payload = decode_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Not a refresh token")

        user_id = payload.get("sub")
        family_id = payload.get("family_id")
        token_jti = payload.get("jti")
        if not (user_id and family_id and token_jti):
            raise HTTPException(status_code=401, detail="Invalid refresh token payload")

        key = self._family_key(user_id, family_id)
        raw = await self.redis.get(key)
        if not raw:
            raise HTTPException(status_code=401, detail="Session expired")

        family = json.loads(raw)
        if family.get("jti") != token_jti:
            # Reuse of a rotated jti — assume the original was stolen and
            # invalidate the entire family.
            await self.redis.delete(key)
            raise HTTPException(
                status_code=401,
                detail="Token reuse detected. All sessions invalidated.",
            )

        absolute_expires_at = datetime.fromisoformat(family["absolute_expires_at"])
        if datetime.now(timezone.utc) >= absolute_expires_at:
            await self.redis.delete(key)
            raise HTTPException(
                status_code=401,
                detail="Session expired, please log in again",
            )

        user = await self.db.scalar(select(User).where(User.id == uuid.UUID(user_id)))
        if not user or not user.is_active:
            await self.redis.delete(key)
            raise HTTPException(status_code=401, detail="User not found or inactive")

        return await self._mint_pair(
            user=user,
            family_id=family_id,
            created_at=datetime.fromisoformat(family["created_at"]),
            absolute_expires_at=absolute_expires_at,
            sliding_days=int(family.get("sliding_days", settings.REFRESH_TOKEN_EXPIRE_DAYS)),
        )

    async def _mint_pair(
        self,
        *,
        user: User,
        family_id: str,
        created_at: datetime,
        absolute_expires_at: datetime,
        sliding_days: int,
    ) -> TokenResponse:
        access_token, _access_jti, _access_exp = create_access_token(user, family_id)
        refresh_token, refresh_jti, refresh_exp = create_refresh_token(
            str(user.id),
            family_id,
            sliding_days=sliding_days,
            absolute_expires_at=absolute_expires_at,
        )

        ttl_seconds = max(int((refresh_exp - datetime.now(timezone.utc)).total_seconds()), 1)
        record = json.dumps(
            {
                "jti": refresh_jti,
                "created_at": created_at.isoformat(),
                "absolute_expires_at": absolute_expires_at.isoformat(),
                "sliding_days": sliding_days,
            }
        )
        await self.redis.set(self._family_key(str(user.id), family_id), record, ex=ttl_seconds)

        return TokenResponse(access_token=access_token, refresh_token=refresh_token)

    # ── logout ──────────────────────────────────────────────────────────────

    async def logout(
        self,
        access_jti: str,
        access_exp: datetime,
        user_id: str | None = None,
        family_id: str | None = None,
    ) -> None:
        ttl = max(int((access_exp - datetime.now(timezone.utc)).total_seconds()), 1)
        await self.redis.set(self._blacklist_key(access_jti), "1", ex=ttl)

        # Revoke this session's refresh family so the refresh token can't be
        # replayed even if it was exfiltrated. family_id rides in the access
        # token (available here); the refresh cookie is path-scoped and never
        # reaches /auth/logout. Tokens minted before this claim existed simply
        # skip family revocation — the cookie clear still ends the session.
        if user_id and family_id:
            await self.redis.delete(self._family_key(user_id, family_id))

    async def logout_all_sessions(self, user_id: str) -> None:
        pattern = f"refresh:{user_id}:*"
        cursor = 0
        while True:
            cursor, keys = await self.redis.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                await self.redis.delete(*keys)
            if cursor == 0:
                break

    # ── password reset / change ──────────────────────────────────────────────

    async def reset_password(self, user: User, new_password: str) -> None:
        """Set a new password hash and wipe every session. Commits the pending
        transaction (which also includes the reset token's burn flagged by the
        caller), then revokes all refresh families so any stolen session dies.
        No session is reissued — the (anonymous) caller logs in afresh."""
        user.hashed_password = hash_password(new_password)
        await self.db.commit()
        await self.logout_all_sessions(str(user.id))

    async def change_password(
        self, user: User, old_password: str, new_password: str
    ) -> TokenResponse:
        """Verify the current password, set the new hash, then revoke every
        session and reissue a fresh one for the caller — so other devices are
        logged out while this request stays authenticated on a rotated pair."""
        if not verify_password(old_password, user.hashed_password):
            raise HTTPException(status_code=400, detail="Invalid current password")
        user.hashed_password = hash_password(new_password)
        await self.db.commit()
        await self.logout_all_sessions(str(user.id))
        return await self.issue_session(user)


async def get_auth_service(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AuthService:
    return AuthService(db, redis)
