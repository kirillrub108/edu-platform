"""Unit tests for HMAC-signed URL generation and verification."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from freezegun import freeze_time

from app.services.signed_url_service import (
    generate_signed_url,
    verify_signed_url,
)

pytestmark = pytest.mark.unit


def _parse(url: str) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}


def test_generate_then_verify_roundtrip() -> None:
    url = generate_signed_url("videos/a.mp4", "user-123", expires_in=60)
    q = _parse(url)
    assert verify_signed_url("videos/a.mp4", q["uid"], int(q["expires"]), q["sig"]) is True


def test_verify_fails_when_path_tampered() -> None:
    url = generate_signed_url("videos/a.mp4", "user-1", expires_in=60)
    q = _parse(url)
    assert verify_signed_url(
        "videos/EVIL.mp4", q["uid"], int(q["expires"]), q["sig"]
    ) is False


def test_verify_fails_when_signature_tampered() -> None:
    url = generate_signed_url("videos/a.mp4", "user-1", expires_in=60)
    q = _parse(url)
    bad_sig = "0" * len(q["sig"])
    assert verify_signed_url("videos/a.mp4", q["uid"], int(q["expires"]), bad_sig) is False


def test_verify_fails_on_expired_signature() -> None:
    """Mint at t=0, verify at t=1h+1s — must reject."""
    with freeze_time("2026-01-01 12:00:00"):
        url = generate_signed_url("a.png", "user-1", expires_in=3600)
        q = _parse(url)

    with freeze_time("2026-01-01 13:00:02"):
        assert verify_signed_url("a.png", q["uid"], int(q["expires"]), q["sig"]) is False


def test_normalize_strips_leading_slash_and_backslashes() -> None:
    """The same logical path should verify regardless of leading slash."""
    url = generate_signed_url("/videos/a.mp4", "u", expires_in=60)
    q = _parse(url)
    assert verify_signed_url("videos/a.mp4", q["uid"], int(q["expires"]), q["sig"]) is True
