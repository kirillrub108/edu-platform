"""Sign-up and email-change refuse addresses we already know we cannot reach.

DNS is mocked at `_resolve_has_mail_host` — the single seam between the service
and dnspython — so no test ever touches a resolver. The suppression list is read
through the request's own async session, so rows go in via `db_session`.
"""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_suppression import EmailSuppression, SuppressionReason
from app.models.user import User
from app.services import email_deliverability_service as deliverability

pytestmark = pytest.mark.integration

_REGISTRATION = {
    "password": "password123",
    "full_name": "New Teacher",
    "role": "teacher",
    "accepted_privacy": True,
    "accepted_terms": True,
}


@pytest.fixture(autouse=True)
def dns_says_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default for this module: every domain resolves. Tests that care override."""
    monkeypatch.setattr(deliverability, "_resolve_has_mail_host", _resolver(True))


def _resolver(verdict: bool | None) -> Any:
    async def _resolve(_domain: str) -> bool | None:
        return verdict

    return _resolve


async def _register(client: AsyncClient, email: str) -> Any:
    return await client.post("/api/v1/auth/register", json={**_REGISTRATION, "email": email})


async def _user_exists(db: AsyncSession, email: str) -> bool:
    return await db.scalar(select(User.id).where(User.email == email)) is not None


async def test_domain_without_mx_or_a_is_rejected(
    client: AsyncClient, db_session: AsyncSession, mock_send_email: Any, monkeypatch: Any
) -> None:
    monkeypatch.setattr(deliverability, "_resolve_has_mail_host", _resolver(False))

    resp = await _register(client, "casdsa@dsa.da")

    assert resp.status_code == 422
    assert resp.json()["detail"] == deliverability.UNDELIVERABLE_DOMAIN_CODE
    assert not await _user_exists(db_session, "casdsa@dsa.da")
    mock_send_email.assert_not_called()


async def test_suppressed_address_is_rejected(
    client: AsyncClient, db_session: AsyncSession, mock_send_email: Any
) -> None:
    db_session.add(
        EmailSuppression(email="bounced@example.com", reason=SuppressionReason.hard_bounce)
    )
    await db_session.flush()

    resp = await _register(client, "bounced@example.com")

    assert resp.status_code == 422
    assert resp.json()["detail"] == deliverability.SUPPRESSED_EMAIL_CODE
    assert not await _user_exists(db_session, "bounced@example.com")
    mock_send_email.assert_not_called()


async def test_suppression_lookup_ignores_case(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    db_session.add(EmailSuppression(email="mixed@example.com", reason=SuppressionReason.complaint))
    await db_session.flush()

    resp = await _register(client, "Mixed@Example.com")

    assert resp.status_code == 422
    assert resp.json()["detail"] == deliverability.SUPPRESSED_EMAIL_CODE


async def test_dns_outage_lets_registration_through(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: Any
) -> None:
    """Fail-open: a resolver we cannot reach is our problem, not the user's."""
    monkeypatch.setattr(deliverability, "_resolve_has_mail_host", _resolver(None))

    resp = await _register(client, "unlucky@example.com")

    assert resp.status_code == 201
    assert await _user_exists(db_session, "unlucky@example.com")


async def test_deliverable_address_registers(
    client: AsyncClient, db_session: AsyncSession, mock_send_email: Any
) -> None:
    resp = await _register(client, "fine@example.com")

    assert resp.status_code == 201
    assert await _user_exists(db_session, "fine@example.com")
    mock_send_email.assert_called_once()


async def test_non_ascii_domain_is_probed_as_punycode(
    client: AsyncClient, monkeypatch: Any
) -> None:
    """A Cyrillic domain must reach the resolver IDNA-encoded — sending it raw
    would raise, land in fail-open, and mask a genuinely dead domain."""
    seen: list[str] = []

    async def _resolve(domain: str) -> bool:
        seen.append(domain)
        return True

    monkeypatch.setattr(deliverability, "_resolve_has_mail_host", _resolve)

    resp = await _register(client, "ivan@почта.рф")

    assert resp.status_code == 201
    assert seen == ["xn--80a1acny.xn--p1ai"]


async def test_resend_verification_refuses_a_bouncing_address(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    """The account's own address started bouncing: resending is pointless, so
    the SPA is steered to the change-email flow by a 422 instead."""
    teacher_user.email_verified = False
    db_session.add(EmailSuppression(email=teacher_user.email, reason=SuppressionReason.hard_bounce))
    await db_session.flush()

    resp = await client.post("/api/v1/auth/resend-verification", cookies=teacher_token)

    assert resp.status_code == 422
    assert resp.json()["detail"] == deliverability.SUPPRESSED_EMAIL_CODE
