"""Social sign-in (Google, Yandex) over Authorization Code + PKCE.

Shape of the flow
-----------------
``start``    mints a state + PKCE verifier, parks them in Redis under
             ``oauth:state:{state}`` and returns the provider's authorize URL.
``callback`` consumes the state atomically (GETDEL - a replayed or forged state
             finds nothing), exchanges the code, reads the profile, and lands in
             one of three branches:

  A. the identity is already linked -> issue a session;
  B. no identity, but the email is a known local account -> link and issue;
  C. neither -> no user is created here (role and the personal-data consents are
     still missing). A one-shot ticket goes into Redis and the SPA finishes the
     registration through ``complete``.

Nothing here mints its own session primitives: every successful branch ends in
``AuthService.issue_session``, i.e. the same refresh family the password login
uses. The caller (router) then writes the usual three cookies.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlencode

import httpx
import structlog
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    CONSENT_POLICY_VERSION,
    OAUTH_HTTP_TIMEOUT_SECONDS,
    OAUTH_PENDING_TICKET_TTL_SECONDS,
    OAUTH_PKCE_VERIFIER_BYTES,
    OAUTH_STATE_BYTES,
    OAUTH_STATE_TTL_SECONDS,
    OAUTH_TICKET_BYTES,
)
from app.models.oauth_account import OAuthAccount
from app.models.user import User, UserRole
from app.schemas.auth import is_disposable_domain
from app.schemas.oauth import OAuthProfile, PendingTicket, StartedFlow

logger = structlog.get_logger()

ProviderName = Literal["google", "yandex"]


class OAuthError(Exception):
    """Sign-in could not complete. ``reason`` is a stable machine code that the
    callback appends to the SPA redirect (?oauth=0&reason=...)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Provider:
    name: ProviderName
    authorize_url: str
    token_url: str
    userinfo_url: str
    scope: str
    # Yandex wants `Authorization: OAuth <token>` on its info endpoint; Google
    # is a normal bearer resource server.
    userinfo_auth_scheme: str


_PROVIDERS: dict[str, Provider] = {
    "google": Provider(
        name="google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        userinfo_url="https://openidconnect.googleapis.com/v1/userinfo",
        scope="openid email profile",
        userinfo_auth_scheme="Bearer",
    ),
    "yandex": Provider(
        name="yandex",
        authorize_url="https://oauth.yandex.ru/authorize",
        token_url="https://oauth.yandex.ru/token",
        userinfo_url="https://login.yandex.ru/info?format=json",
        scope="login:email login:info",
        userinfo_auth_scheme="OAuth",
    ),
}


def _credentials(provider: ProviderName) -> tuple[str, str]:
    if provider == "google":
        return settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET
    return settings.YANDEX_CLIENT_ID, settings.YANDEX_CLIENT_SECRET


def get_provider(provider: str) -> Provider | None:
    """The configured provider, or None when unknown or missing credentials."""
    known = _PROVIDERS.get(provider)
    if known is None:
        return None
    client_id, client_secret = _credentials(known.name)
    return known if client_id and client_secret else None


def redirect_uri(provider: ProviderName) -> str:
    base = (settings.OAUTH_REDIRECT_BASE_URL or settings.BASE_URL).rstrip("/")
    return f"{base}/api/v1/auth/oauth/{provider}/callback"


def normalize_email(email: str) -> str:
    """Case-folded, whitespace-trimmed address. Providers are inconsistent about
    the case they report and users type their address either way at signup, so
    lookups must not depend on it."""
    return email.strip().lower()


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _state_key(state: str) -> str:
    return f"oauth:state:{state}"


def _ticket_key(ticket: str) -> str:
    return f"oauth:pending:{ticket}"


# -- start --------------------------------------------------------------------


async def start(
    redis: Redis,
    provider: Provider,
    *,
    remember_me: bool,
    next_path: str | None,
) -> str:
    """Park state + PKCE verifier in Redis and return the authorize URL."""
    state = secrets.token_urlsafe(OAUTH_STATE_BYTES)
    verifier = secrets.token_urlsafe(OAUTH_PKCE_VERIFIER_BYTES)
    flow = StartedFlow(
        provider=provider.name,
        code_verifier=verifier,
        remember_me=remember_me,
        next=next_path,
        created_at=datetime.now(timezone.utc),
    )
    await redis.set(_state_key(state), flow.model_dump_json(), ex=OAUTH_STATE_TTL_SECONDS)

    client_id, _ = _credentials(provider.name)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri(provider.name),
        "scope": provider.scope,
        "state": state,
        "code_challenge": _pkce_challenge(verifier),
        "code_challenge_method": "S256",
    }
    return f"{provider.authorize_url}?{urlencode(params)}"


async def consume_state(redis: Redis, provider: Provider, state: str) -> StartedFlow:
    """One-shot read of the parked flow. GETDEL is atomic, so a replayed state
    (double-submitted callback, attacker replay) finds nothing the second time."""
    raw = await redis.getdel(_state_key(state))
    if not raw:
        raise OAuthError("invalid_state")
    flow = StartedFlow.model_validate_json(raw)
    if flow.provider != provider.name:
        # State minted for another provider - never honour it.
        raise OAuthError("invalid_state")
    return flow


# -- provider round trips -----------------------------------------------------


async def _post_json(url: str, data: dict[str, str]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=OAUTH_HTTP_TIMEOUT_SECONDS) as client:
        resp = await client.post(url, data=data, headers={"Accept": "application/json"})
    if resp.status_code >= 400:
        raise OAuthError("provider_error")
    try:
        return resp.json()
    except ValueError as exc:
        raise OAuthError("provider_error") from exc


async def _get_json(url: str, authorization: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=OAUTH_HTTP_TIMEOUT_SECONDS) as client:
        resp = await client.get(
            url,
            headers={"Authorization": authorization, "Accept": "application/json"},
        )
    if resp.status_code >= 400:
        raise OAuthError("provider_error")
    try:
        return resp.json()
    except ValueError as exc:
        raise OAuthError("provider_error") from exc


async def fetch_profile(provider: Provider, code: str, code_verifier: str) -> OAuthProfile:
    """Exchange the code and read the profile. Any transport / protocol problem
    surfaces as an OAuthError so the callback can redirect instead of 500."""
    client_id, client_secret = _credentials(provider.name)
    try:
        token = await _post_json(
            provider.token_url,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri(provider.name),
                "client_id": client_id,
                "client_secret": client_secret,
                "code_verifier": code_verifier,
            },
        )
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OAuthError("provider_error")
        info = await _get_json(
            provider.userinfo_url,
            f"{provider.userinfo_auth_scheme} {access_token}",
        )
    except httpx.HTTPError as exc:
        raise OAuthError("provider_unreachable") from exc

    return _parse_profile(provider, info)


def _parse_profile(provider: Provider, info: dict[str, Any]) -> OAuthProfile:
    if provider.name == "google":
        subject = info.get("sub")
        email = info.get("email")
        # Google is explicit about mailbox ownership; anything but a true here
        # (including the string "true" some clients send) is unproven.
        verified = info.get("email_verified") in (True, "true")
        full_name = info.get("name")
    else:
        subject = info.get("id")
        emails = info.get("emails")
        fallback = emails[0] if isinstance(emails, list) and emails else None
        email = info.get("default_email") or fallback
        # Yandex exposes no per-address verification flag. A Yandex ID account
        # can only exist on a mailbox the user controls, so default_email is
        # taken as proven - see docs/DECISIONS.md.
        verified = True
        full_name = info.get("real_name") or info.get("display_name")

    if not isinstance(subject, (str, int)) or not str(subject).strip():
        raise OAuthError("provider_error")
    if not isinstance(email, str) or "@" not in email:
        raise OAuthError("no_email")
    if not verified:
        raise OAuthError("email_unverified")

    return OAuthProfile(
        provider=provider.name,
        provider_user_id=str(subject),
        email=normalize_email(email),
        full_name=full_name if isinstance(full_name, str) and full_name.strip() else None,
    )


# -- account resolution (branches A / B / C) ----------------------------------


async def _user_by_email(db: AsyncSession, email: str) -> User | None:
    # func.lower on the column too: pre-existing rows may hold a mixed-case address.
    return await db.scalar(select(User).where(func.lower(User.email) == email))


def _assert_usable(user: User) -> None:
    if not user.is_active:
        raise OAuthError("account_disabled")


async def resolve_user(db: AsyncSession, profile: OAuthProfile) -> User | None:
    """Branch A/B: the local user this identity signs in as, or None when both
    the identity and the email are unknown (branch C - the caller issues a
    pending ticket instead)."""
    identity = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.provider == profile.provider,
            OAuthAccount.provider_user_id == profile.provider_user_id,
        )
    )
    if identity is not None:
        # select() (not db.get) so the global soft-delete filter applies: a
        # soft-deleted account must not be resurrected by a social login.
        user = await db.scalar(select(User).where(User.id == identity.user_id))
        if user is None:
            raise OAuthError("account_disabled")
        _assert_usable(user)
        return user

    user = await _user_by_email(db, profile.email)
    if user is None:
        return None

    _assert_usable(user)
    await link_identity(db, user, profile)
    return user


async def link_identity(db: AsyncSession, user: User, profile: OAuthProfile) -> None:
    """Attach the identity to ``user`` and mark the mailbox proven. Refuses when
    the account already carries a *different* identity of the same provider -
    that means two provider accounts claim one mailbox, which we won't merge."""
    existing = await db.scalar(
        select(OAuthAccount).where(
            OAuthAccount.user_id == user.id,
            OAuthAccount.provider == profile.provider,
        )
    )
    if existing is not None and existing.provider_user_id != profile.provider_user_id:
        raise OAuthError("account_conflict")

    if existing is None:
        db.add(
            OAuthAccount(
                user_id=user.id,
                provider=profile.provider,
                provider_user_id=profile.provider_user_id,
                email=profile.email,
            )
        )
    if not user.email_verified:
        user.email_verified = True
    await db.commit()


# -- branch C: pending registration ticket ------------------------------------


async def issue_ticket(redis: Redis, profile: OAuthProfile) -> str:
    ticket = secrets.token_urlsafe(OAUTH_TICKET_BYTES)
    payload = PendingTicket(
        provider=profile.provider,
        provider_user_id=profile.provider_user_id,
        email=profile.email,
        full_name=profile.full_name,
        created_at=datetime.now(timezone.utc),
    )
    await redis.set(
        _ticket_key(ticket),
        payload.model_dump_json(),
        ex=OAUTH_PENDING_TICKET_TTL_SECONDS,
    )
    return ticket


async def consume_ticket(redis: Redis, ticket: str) -> PendingTicket:
    """Atomic one-shot read. Two tabs finishing the same ticket race here and
    exactly one gets the payload; the other sees invalid_ticket."""
    raw = await redis.getdel(_ticket_key(ticket))
    if not raw:
        raise OAuthError("invalid_ticket")
    return PendingTicket.model_validate_json(raw)


async def create_user(
    db: AsyncSession,
    pending: PendingTicket,
    *,
    role: UserRole,
    accepted_marketing: bool,
    consent_ip: str | None,
) -> User:
    """Finish branch C: a verified-by-provider, password-less account carrying
    the same consent record a password registration writes.

    If the mailbox was registered locally between the callback and this call,
    the identity is linked to that account instead of creating a duplicate.
    """
    if is_disposable_domain(pending.email.split("@")[-1]):
        raise OAuthError("email_not_allowed")

    existing = await _user_by_email(db, pending.email)
    if existing is not None:
        _assert_usable(existing)
        await link_identity(db, existing, _profile_of(pending))
        return existing

    now = datetime.now(timezone.utc)
    user = User(
        email=pending.email,
        hashed_password=None,
        full_name=pending.full_name,
        role=role,
        email_verified=True,
        pdn_consent_at=now,
        terms_accepted_at=now,
        marketing_consent=accepted_marketing,
        marketing_consent_at=now if accepted_marketing else None,
        consent_policy_version=CONSENT_POLICY_VERSION,
        consent_ip=consent_ip,
    )
    db.add(user)
    await db.flush()
    db.add(
        OAuthAccount(
            user_id=user.id,
            provider=pending.provider,
            provider_user_id=pending.provider_user_id,
            email=pending.email,
        )
    )
    await db.commit()
    await db.refresh(user)
    return user


def _profile_of(pending: PendingTicket) -> OAuthProfile:
    return OAuthProfile(
        provider=pending.provider,
        provider_user_id=pending.provider_user_id,
        email=pending.email,
        full_name=pending.full_name,
    )


def dashboard_path(user: User) -> str:
    return "/student/dashboard" if user.role == UserRole.student else "/dashboard"
