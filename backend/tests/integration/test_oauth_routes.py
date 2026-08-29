"""Social sign-in routes end to end. The two provider round trips (token
exchange, userinfo) are stubbed at the HTTP boundary — _post_json / _get_json —
so state handling, branching and profile parsing all stay under test."""

from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.config import settings
from app.constants import CONSENT_POLICY_VERSION
from app.models.oauth_account import OAuthAccount
from app.models.user import User, UserRole
from app.services import oauth_service

pytestmark = pytest.mark.integration


def _email() -> str:
    return f"oauth-{uuid.uuid4().hex[:10]}@example.com"


def _sub() -> str:
    return f"sub-{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _configure_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_ID", "google-client-id")
    monkeypatch.setattr(settings, "GOOGLE_CLIENT_SECRET", "google-client-secret")
    monkeypatch.setattr(settings, "YANDEX_CLIENT_ID", "yandex-client-id")
    monkeypatch.setattr(settings, "YANDEX_CLIENT_SECRET", "yandex-client-secret")


def _stub_provider(monkeypatch: pytest.MonkeyPatch, userinfo: dict[str, Any] | Exception) -> None:
    async def _post_json(url: str, data: dict[str, str]) -> dict[str, Any]:
        return {"access_token": "provider-access-token"}

    async def _get_json(url: str, authorization: str) -> dict[str, Any]:
        if isinstance(userinfo, Exception):
            raise userinfo
        return userinfo

    monkeypatch.setattr(oauth_service, "_post_json", _post_json)
    monkeypatch.setattr(oauth_service, "_get_json", _get_json)


def _google_info(email: str, sub: str, *, verified: bool = True) -> dict[str, Any]:
    return {"sub": sub, "email": email, "email_verified": verified, "name": "Ada Lovelace"}


async def _begin(client: AsyncClient, provider: str = "google") -> str:
    """Run /start and return the state parked in Redis."""
    resp = await client.post(f"/api/v1/auth/oauth/{provider}/start", json={})
    assert resp.status_code == 200
    query = parse_qs(urlparse(resp.json()["authorize_url"]).query)
    return query["state"][0]


async def _callback(client: AsyncClient, state: str, provider: str = "google") -> Any:
    return await client.get(
        f"/api/v1/auth/oauth/{provider}/callback",
        params={"code": "auth-code", "state": state},
    )


def _reason(response: Any) -> str:
    return parse_qs(urlparse(response.headers["location"]).query)["reason"][0]


# -- start --------------------------------------------------------------------


async def test_start_returns_pkce_authorize_url(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/oauth/google/start", json={"remember_me": False})
    assert resp.status_code == 200
    query = parse_qs(urlparse(resp.json()["authorize_url"]).query)
    assert query["client_id"] == ["google-client-id"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["response_type"] == ["code"]
    assert query["state"][0]


async def test_start_unknown_provider_is_404(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/oauth/facebook/start", json={})
    assert resp.status_code == 404


async def test_start_unconfigured_provider_is_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "YANDEX_CLIENT_ID", "")
    resp = await client.post("/api/v1/auth/oauth/yandex/start", json={})
    assert resp.status_code == 404


async def test_start_rejects_offsite_next(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/oauth/google/start", json={"next": "//evil.example.com"})
    assert resp.status_code == 422


# -- branch A: known identity -------------------------------------------------


async def test_callback_known_identity_logs_in(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    email, sub = _email(), _sub()
    user = User(
        email=email,
        hashed_password=None,
        role=UserRole.student,
        email_verified=True,
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OAuthAccount(user_id=user.id, provider="google", provider_user_id=sub, email=email)
    )
    await db_session.flush()

    _stub_provider(monkeypatch, _google_info(email, sub))
    resp = await _callback(client, await _begin(client))

    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/student/dashboard")
    assert "access_token" in resp.cookies
    assert "csrf_token" in resp.cookies
    # No duplicate identity row was written.
    rows = (
        await db_session.scalars(select(OAuthAccount).where(OAuthAccount.provider_user_id == sub))
    ).all()
    assert len(rows) == 1


async def test_callback_inactive_account_is_refused(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    email, sub = _email(), _sub()
    user = User(email=email, hashed_password=None, role=UserRole.teacher, is_active=False)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OAuthAccount(user_id=user.id, provider="google", provider_user_id=sub, email=email)
    )
    await db_session.flush()

    _stub_provider(monkeypatch, _google_info(email, sub))
    resp = await _callback(client, await _begin(client))

    assert resp.status_code == 302
    assert _reason(resp) == "account_disabled"
    assert "access_token" not in resp.cookies


# -- branch B: known email, new identity --------------------------------------


async def test_callback_links_existing_email_and_verifies_it(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    email, sub = _email(), _sub()
    user = User(
        email=email,
        hashed_password="argon2-hash",
        role=UserRole.teacher,
        email_verified=False,
    )
    db_session.add(user)
    await db_session.flush()

    # Provider reports the same mailbox in a different case — must still match.
    _stub_provider(monkeypatch, _google_info(email.upper(), sub))
    resp = await _callback(client, await _begin(client))

    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/dashboard")
    await db_session.refresh(user)
    assert user.email_verified is True
    identity = await db_session.scalar(select(OAuthAccount).where(OAuthAccount.user_id == user.id))
    assert identity is not None and identity.provider_user_id == sub
    # No second user was created for the same mailbox.
    users = (await db_session.scalars(select(User).where(User.email == email))).all()
    assert len(users) == 1


async def test_callback_links_mixed_case_row_in_db(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other direction: the *stored* address has capitals (a pre-OAuth
    signup), the provider reports lower case. Branch B must still find it —
    otherwise a social login silently forks a second account on one mailbox."""
    stored = f"Ada.Lovelace-{uuid.uuid4().hex[:8]}@Example.COM"
    user = User(email=stored, hashed_password="argon2-hash", role=UserRole.teacher)
    db_session.add(user)
    await db_session.flush()

    _stub_provider(monkeypatch, _google_info(stored.lower(), _sub()))
    resp = await _callback(client, await _begin(client))

    assert resp.status_code == 302
    assert resp.headers["location"].endswith("/dashboard")
    identity = await db_session.scalar(select(OAuthAccount).where(OAuthAccount.user_id == user.id))
    assert identity is not None
    # Exactly one user for this mailbox, in either case spelling.
    users = (
        await db_session.scalars(select(User).where(func.lower(User.email) == stored.lower()))
    ).all()
    assert len(users) == 1
    assert users[0].id == user.id


async def test_callback_refuses_second_identity_of_same_provider(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _email()
    user = User(email=email, hashed_password="argon2-hash", role=UserRole.teacher)
    db_session.add(user)
    await db_session.flush()
    db_session.add(
        OAuthAccount(user_id=user.id, provider="google", provider_user_id=_sub(), email=email)
    )
    await db_session.flush()

    _stub_provider(monkeypatch, _google_info(email, _sub()))
    resp = await _callback(client, await _begin(client))

    assert resp.status_code == 302
    assert _reason(resp) == "account_conflict"


# -- branch C: pending ticket + complete --------------------------------------


async def _pending_ticket(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, email: str, sub: str
) -> str:
    _stub_provider(monkeypatch, _google_info(email, sub))
    resp = await _callback(client, await _begin(client))
    assert resp.status_code == 302
    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert query["provider"] == ["google"]
    return query["oauth_pending"][0]


async def test_callback_unknown_identity_issues_ticket_without_creating_user(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _email()
    ticket = await _pending_ticket(client, monkeypatch, email, _sub())
    assert ticket
    assert await db_session.scalar(select(User).where(User.email == email)) is None


async def test_complete_creates_verified_user_with_consents(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _email()
    ticket = await _pending_ticket(client, monkeypatch, email, _sub())

    resp = await client.post(
        "/api/v1/auth/oauth/complete",
        json={
            "ticket": ticket,
            "role": "student",
            "pdn_consent": True,
            "offer_consent": True,
            "marketing_consent": True,
        },
        headers={"X-Forwarded-For": "203.0.113.9"},
    )
    assert resp.status_code == 200
    assert resp.json()["redirect"] == "/student/dashboard"
    assert "access_token" in resp.cookies

    user = await db_session.scalar(select(User).where(User.email == email))
    assert user is not None
    assert user.email_verified is True
    assert user.hashed_password is None
    assert user.role == UserRole.student
    assert user.pdn_consent_at is not None
    assert user.terms_accepted_at is not None
    assert user.marketing_consent is True
    assert user.consent_policy_version == CONSENT_POLICY_VERSION
    assert user.consent_ip == "203.0.113.9"


async def test_complete_requires_both_consents(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _email()
    ticket = await _pending_ticket(client, monkeypatch, email, _sub())
    resp = await client.post(
        "/api/v1/auth/oauth/complete",
        json={"ticket": ticket, "role": "teacher", "pdn_consent": True},
    )
    assert resp.status_code == 422
    assert await db_session.scalar(select(User).where(User.email == email)) is None


async def test_ticket_is_single_use(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two tabs finishing one ticket: the second gets 400, and only one user
    row exists afterwards."""
    email = _email()
    ticket = await _pending_ticket(client, monkeypatch, email, _sub())
    body = {"ticket": ticket, "role": "teacher", "pdn_consent": True, "offer_consent": True}

    first = await client.post("/api/v1/auth/oauth/complete", json=body)
    second = await client.post("/api/v1/auth/oauth/complete", json=body)

    assert first.status_code == 200
    assert second.status_code == 400
    assert second.json()["detail"] == "invalid_ticket"
    users = (await db_session.scalars(select(User).where(User.email == email))).all()
    assert len(users) == 1


# -- state and provider failures ----------------------------------------------


async def test_state_is_single_use(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_provider(monkeypatch, _google_info(_email(), _sub()))
    state = await _begin(client)
    assert (await _callback(client, state)).status_code == 302
    replay = await _callback(client, state)
    assert _reason(replay) == "invalid_state"


async def test_unknown_state_is_refused(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_provider(monkeypatch, _google_info(_email(), _sub()))
    resp = await _callback(client, "state-that-was-never-issued")
    assert _reason(resp) == "invalid_state"


async def test_state_from_another_provider_is_refused(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_provider(monkeypatch, _google_info(_email(), _sub()))
    state = await _begin(client, provider="google")
    resp = await _callback(client, state, provider="yandex")
    assert _reason(resp) == "invalid_state"


async def test_user_declined_on_provider(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/oauth/google/callback", params={"error": "access_denied"})
    assert resp.status_code == 302
    assert _reason(resp) == "access_denied"


async def test_unverified_provider_email_is_refused(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _email()
    _stub_provider(monkeypatch, _google_info(email, _sub(), verified=False))
    resp = await _callback(client, await _begin(client))
    assert _reason(resp) == "email_unverified"
    assert await db_session.scalar(select(User).where(User.email == email)) is None


async def test_provider_transport_failure_redirects(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import httpx

    _stub_provider(monkeypatch, httpx.ConnectTimeout("boom"))
    resp = await _callback(client, await _begin(client))
    assert resp.status_code == 302
    assert _reason(resp) == "provider_unreachable"


async def test_yandex_profile_is_accepted_as_verified(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    email = _email()
    _stub_provider(
        monkeypatch,
        {"id": _sub(), "default_email": email.upper(), "real_name": "Ада Лавлейс"},
    )
    resp = await _callback(client, await _begin(client, provider="yandex"), provider="yandex")
    assert resp.status_code == 302
    query = parse_qs(urlparse(resp.headers["location"]).query)
    assert "oauth_pending" in query


# -- billing bootstrap is unchanged by the sign-in path -----------------------


async def test_linking_does_not_double_grant_welcome_credits(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Welcome credits are granted lazily by get_or_create_account (upsert keyed
    on owner_id), never at registration. Linking an identity to an account that
    already drew them must not produce a second GRANT."""
    from app.models.credit import CreditOperation, CreditTransaction
    from app.services import billing_service

    email = _email()
    user = User(email=email, hashed_password="argon2-hash", role=UserRole.teacher)
    db_session.add(user)
    await db_session.flush()

    account = await billing_service.get_or_create_account(db_session, user.id)
    granted = account.balance

    _stub_provider(monkeypatch, _google_info(email, _sub()))
    assert (await _callback(client, await _begin(client))).status_code == 302

    after = await billing_service.get_or_create_account(db_session, user.id)
    assert after.balance == granted
    grants = (
        await db_session.scalars(
            select(CreditTransaction).where(
                CreditTransaction.account_id == account.id,
                CreditTransaction.operation == CreditOperation.GRANT,
            )
        )
    ).all()
    assert len(grants) <= 1


async def test_oauth_created_user_gets_the_same_welcome_credits(
    client: AsyncClient, db_session: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An account born through `complete` bootstraps its billing exactly like a
    password signup — no path grants credits at registration time."""
    from app.constants import PLAN_CONFIGS
    from app.services import billing_service

    email = _email()
    ticket = await _pending_ticket(client, monkeypatch, email, _sub())
    resp = await client.post(
        "/api/v1/auth/oauth/complete",
        json={"ticket": ticket, "role": "teacher", "pdn_consent": True, "offer_consent": True},
    )
    assert resp.status_code == 200

    user = await db_session.scalar(select(User).where(User.email == email))
    account = await billing_service.get_or_create_account(db_session, user.id)
    assert account.balance == PLAN_CONFIGS["free"]["onetime_credits"]


# -- password login against a social-only account -----------------------------


async def test_password_login_on_passwordless_account_is_401(
    client: AsyncClient, db_session: Any
) -> None:
    email = _email()
    db_session.add(
        User(email=email, hashed_password=None, role=UserRole.teacher, email_verified=True)
    )
    await db_session.flush()

    resp = await client.post("/api/v1/auth/login", json={"email": email, "password": "whatever123"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid credentials"
