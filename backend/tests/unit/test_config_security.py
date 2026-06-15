"""Pre-prod hardening: SECRET_KEY fail-fast (config.py) and the CORS
wildcard+credentials guard (main.py)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.unit


def _settings(**overrides: object):
    # _env_file=None so a stray .env isn't read; DATABASE_URL comes from the
    # test env (pytest-env). Each test overrides only what it cares about.
    from app.config import Settings

    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


# ── SECRET_KEY fail-fast ─────────────────────────────────────────────────────


def test_secret_key_required_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        _settings()


def test_default_change_me_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        _settings(SECRET_KEY="change-me", ENVIRONMENT="production")


def test_prod_placeholder_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        _settings(SECRET_KEY="CHANGE_ME_OPENSSL_RAND_HEX_32", ENVIRONMENT="production")


def test_short_secret_key_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        _settings(SECRET_KEY="too-short", ENVIRONMENT="production")


def test_weak_secret_key_allowed_in_development() -> None:
    # Dev keeps `cp .env.example .env` working — the placeholder still boots.
    settings = _settings(SECRET_KEY="change-me", ENVIRONMENT="development")
    assert settings.SECRET_KEY == "change-me"


def test_strong_secret_key_accepted_in_production() -> None:
    strong = "a" * 48
    settings = _settings(SECRET_KEY=strong, ENVIRONMENT="production")
    assert settings.SECRET_KEY == strong


def test_weak_key_longer_than_32_chars_rejected_in_production() -> None:
    # "your-super-secret-key-change-in-production" is 42 chars (>= 32) but is
    # in _WEAK_SECRET_KEYS — length alone must not be the sole guard.
    with pytest.raises(ValidationError):
        _settings(
            SECRET_KEY="your-super-secret-key-change-in-production",
            ENVIRONMENT="production",
        )


def test_exactly_32_chars_accepted_in_production() -> None:
    # Boundary: len == 32 is the minimum valid length (< 32 is rejected).
    settings = _settings(SECRET_KEY="x" * 32, ENVIRONMENT="production")
    assert len(settings.SECRET_KEY) == 32


def test_exactly_31_chars_rejected_in_production() -> None:
    # Off-by-one: len == 31 must be rejected.
    with pytest.raises(ValidationError):
        _settings(SECRET_KEY="x" * 31, ENVIRONMENT="production")


def test_empty_secret_key_rejected_in_production() -> None:
    with pytest.raises(ValidationError):
        _settings(SECRET_KEY="", ENVIRONMENT="production")


# ── CORS wildcard + credentials guard ────────────────────────────────────────


def test_cors_wildcard_raises_in_production() -> None:
    from app.main import _assert_cors_allowlist_safe

    with pytest.raises(RuntimeError):
        _assert_cors_allowlist_safe(["*"], "production")


def test_cors_wildcard_allowed_in_development() -> None:
    from app.main import _assert_cors_allowlist_safe

    # Tolerated in dev (credentials get disabled), and reports allow_all=True.
    assert _assert_cors_allowlist_safe(["*"], "development") is True


def test_cors_explicit_allowlist_ok_in_production() -> None:
    from app.main import _assert_cors_allowlist_safe

    assert _assert_cors_allowlist_safe(["https://edllm.ru"], "production") is False
