"""Pure helpers of the OAuth service: email normalization, the disposable-domain
gate shared with password registration, PKCE derivation and profile parsing."""

from __future__ import annotations

import base64
import hashlib

import pytest

from app.schemas.auth import is_disposable_domain
from app.services.oauth_service import (
    _PROVIDERS,
    OAuthError,
    _parse_profile,
    _pkce_challenge,
    normalize_email,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("User@Example.COM", "user@example.com"),
        ("  spaced@example.com  ", "spaced@example.com"),
        ("already@lower.ru", "already@lower.ru"),
    ],
)
def test_normalize_email(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


def test_disposable_domain_gate() -> None:
    assert is_disposable_domain("mailinator.com") is True
    # Subdomains of a blocked provider are blocked too.
    assert is_disposable_domain("mail.mailinator.com") is True
    assert is_disposable_domain("example.com") is False


def test_pkce_challenge_is_base64url_sha256() -> None:
    verifier = "abc123-verifier"
    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    challenge = _pkce_challenge(verifier)
    assert challenge == expected
    assert "=" not in challenge


def test_google_profile_is_normalized() -> None:
    profile = _parse_profile(
        _PROVIDERS["google"],
        {"sub": "42", "email": "Ada@Example.COM", "email_verified": True, "name": "Ada"},
    )
    assert profile.provider_user_id == "42"
    assert profile.email == "ada@example.com"
    assert profile.full_name == "Ada"


def test_google_unverified_email_is_rejected() -> None:
    with pytest.raises(OAuthError) as exc:
        _parse_profile(
            _PROVIDERS["google"],
            {"sub": "42", "email": "ada@example.com", "email_verified": False},
        )
    assert exc.value.reason == "email_unverified"


def test_yandex_profile_is_treated_as_verified() -> None:
    profile = _parse_profile(
        _PROVIDERS["yandex"],
        {"id": 7, "default_email": "Ada@Yandex.RU", "real_name": "Ада"},
    )
    assert profile.provider_user_id == "7"
    assert profile.email == "ada@yandex.ru"


def test_profile_without_email_is_rejected() -> None:
    with pytest.raises(OAuthError) as exc:
        _parse_profile(_PROVIDERS["yandex"], {"id": "7"})
    assert exc.value.reason == "no_email"
