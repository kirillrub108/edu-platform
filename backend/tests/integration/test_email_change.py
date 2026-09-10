"""Email change: request, confirm, and the ways it must refuse.

DNS is mocked at `_resolve_has_mail_host` so no test touches a resolver.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.email_suppression import EmailSuppression, SuppressionReason
from app.models.user import User, UserRole
from app.services import account_service
from app.services import email_deliverability_service as deliverability
from app.services.auth_service import hash_password

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def dns_says_yes(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _resolve(_domain: str) -> bool:
        return True

    monkeypatch.setattr(deliverability, "_resolve_has_mail_host", _resolve)


async def _request_change(client: AsyncClient, cookies: dict[str, str], new_email: str) -> Any:
    return await client.post(
        "/api/v1/auth/change-email", json={"new_email": new_email}, cookies=cookies
    )


async def _confirm(client: AsyncClient, token: str) -> Any:
    return await client.post("/api/v1/auth/confirm-email-change", json={"token": token})


async def test_change_request_mails_the_new_address_only(
    client: AsyncClient,
    teacher_user: User,
    teacher_token: dict[str, str],
    mock_send_email: Any,
) -> None:
    """The old address is never notified — it is, by premise, unreachable."""
    resp = await _request_change(client, teacher_token, "brand-new@example.com")

    assert resp.status_code == 204
    mock_send_email.assert_called_once()
    kwargs = mock_send_email.call_args.kwargs
    assert kwargs["to"] == "brand-new@example.com"
    assert kwargs["template_name"] == "change_email.html"


async def test_change_does_not_touch_the_account_until_confirmed(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User, teacher_token: Any
) -> None:
    original = teacher_user.email
    await _request_change(client, teacher_token, "not-yet@example.com")

    await db_session.refresh(teacher_user)
    assert teacher_user.email == original


async def test_confirm_applies_address_verifies_and_clears_bounce(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    teacher_user.email_verified = False
    teacher_user.email_bounced_at = datetime.now(timezone.utc)
    teacher_user.email_bounce_reason = "hard_bounce"
    await db_session.flush()
    token = account_service.generate_email_change_token(
        str(teacher_user.id), teacher_user.email, "moved@example.com"
    )

    resp = await _confirm(client, token)

    assert resp.status_code == 200
    assert resp.json()["email"] == "moved@example.com"
    await db_session.refresh(teacher_user)
    assert teacher_user.email == "moved@example.com"
    assert teacher_user.email_verified is True
    assert teacher_user.email_bounced_at is None
    assert teacher_user.email_bounce_reason is None


async def test_confirm_clears_this_browsers_session_cookies(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    """Revoking the refresh family leaves an already-issued access token valid
    until it expires, so the confirm response must clear the cookies too."""
    token = account_service.generate_email_change_token(
        str(teacher_user.id), teacher_user.email, "signed-out@example.com"
    )

    resp = await _confirm(client, token)

    assert resp.status_code == 200
    cleared = {
        c.split("=")[0]
        for c in resp.headers.get_list("set-cookie")
        if "Max-Age=0" in c or "1970" in c
    }
    assert {"access_token", "refresh_token", "csrf_token"} <= cleared


async def test_confirm_token_is_single_use(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    token = account_service.generate_email_change_token(
        str(teacher_user.id), teacher_user.email, "once@example.com"
    )

    assert (await _confirm(client, token)).status_code == 200
    second = await _confirm(client, token)

    assert second.status_code == 400
    assert second.json()["detail"] == "invalid_or_expired"


async def test_superseded_token_is_refused(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    """A token minted before an earlier change landed is pinned to the address
    the account no longer has, so it cannot resurrect a stale target."""
    stale = account_service.generate_email_change_token(
        str(teacher_user.id), teacher_user.email, "stale-target@example.com"
    )
    teacher_user.email = "already-moved@example.com"
    await db_session.flush()

    resp = await _confirm(client, stale)

    assert resp.status_code == 400
    await db_session.refresh(teacher_user)
    assert teacher_user.email == "already-moved@example.com"


async def test_change_to_a_taken_address_is_409(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User, teacher_token: Any
) -> None:
    db_session.add(
        User(
            email="taken@example.com",
            hashed_password=hash_password("password123"),
            role=UserRole.teacher,
            is_active=True,
            email_verified=True,
        )
    )
    await db_session.flush()

    resp = await _request_change(client, teacher_token, "taken@example.com")

    assert resp.status_code == 409


async def test_change_to_the_same_address_is_409(
    client: AsyncClient, teacher_user: User, teacher_token: Any
) -> None:
    resp = await _request_change(client, teacher_token, teacher_user.email)
    assert resp.status_code == 409


async def test_change_to_a_suppressed_address_is_422(
    client: AsyncClient, db_session: AsyncSession, teacher_token: Any, mock_send_email: Any
) -> None:
    db_session.add(
        EmailSuppression(email="alsodead@example.com", reason=SuppressionReason.hard_bounce)
    )
    await db_session.flush()

    resp = await _request_change(client, teacher_token, "alsodead@example.com")

    assert resp.status_code == 422
    assert resp.json()["detail"] == deliverability.SUPPRESSED_EMAIL_CODE
    mock_send_email.assert_not_called()


async def test_change_to_a_dead_domain_is_422(
    client: AsyncClient, teacher_token: Any, monkeypatch: Any, mock_send_email: Any
) -> None:
    async def _resolve(_domain: str) -> bool:
        return False

    monkeypatch.setattr(deliverability, "_resolve_has_mail_host", _resolve)

    resp = await _request_change(client, teacher_token, "someone@dsa.da")

    assert resp.status_code == 422
    assert resp.json()["detail"] == deliverability.UNDELIVERABLE_DOMAIN_CODE
    mock_send_email.assert_not_called()


async def test_change_requires_authentication(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/auth/change-email", json={"new_email": "anon@example.com"})
    assert resp.status_code == 401


async def test_confirm_rejects_a_garbage_token(client: AsyncClient) -> None:
    resp = await _confirm(client, "not-a-real-token")
    assert resp.status_code == 400


async def test_suppression_row_for_the_old_address_survives_the_change(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    """The abandoned mailbox is still dead; only the account's warning clears."""
    old = teacher_user.email
    db_session.add(EmailSuppression(email=old, reason=SuppressionReason.hard_bounce))
    await db_session.flush()
    token = account_service.generate_email_change_token(
        str(teacher_user.id), old, "fresh@example.com"
    )

    assert (await _confirm(client, token)).status_code == 200

    still_there = await db_session.scalar(
        select(EmailSuppression).where(EmailSuppression.email == old)
    )
    assert still_there is not None
