"""Unit tests for the email service: Jinja2 rendering, provider selection, and
the Resend provider's success/retry/permanent-error mapping."""

from __future__ import annotations

import httpx
import pytest

from app.services import email_service
from app.services.email_service import (
    EmailDeliveryError,
    ResendProvider,
    build_provider,
    render_template,
)

pytestmark = pytest.mark.unit


# ── Template rendering ────────────────────────────────────────────────────────

def test_render_verify_email_includes_url_and_name() -> None:
    html = render_template(
        "verify_email.html",
        {"full_name": "Alice", "verify_url": "https://x.test/api/v1/auth/verify-email?token=abc"},
    )
    assert "Alice" in html
    assert "https://x.test/api/v1/auth/verify-email?token=abc" in html


def test_render_video_ready_includes_lesson() -> None:
    html = render_template(
        "video_ready.html",
        {"full_name": "Bob", "lesson_title": "Intro", "lesson_url": "https://x.test/lessons/1"},
    )
    assert "Intro" in html
    assert "https://x.test/lessons/1" in html


def test_render_autoescapes_html_in_context() -> None:
    html = render_template(
        "video_ready.html",
        {"full_name": "<script>x</script>", "lesson_title": "t", "lesson_url": "u"},
    )
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


# ── Provider selection ────────────────────────────────────────────────────────

def test_build_provider_returns_resend_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_service.settings, "EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(email_service.settings, "RESEND_API_KEY", "re_test_key")
    provider = build_provider()
    assert isinstance(provider, ResendProvider)


def test_build_provider_missing_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_service.settings, "EMAIL_PROVIDER", "resend")
    monkeypatch.setattr(email_service.settings, "RESEND_API_KEY", "")
    with pytest.raises(RuntimeError):
        build_provider()


def test_build_provider_unknown_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_service.settings, "EMAIL_PROVIDER", "sendgrid")
    with pytest.raises(RuntimeError):
        build_provider()


# ── Resend provider status mapping ────────────────────────────────────────────

class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.text = "body"


def test_resend_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_service.httpx, "post", lambda *a, **k: _Resp(200))
    ResendProvider("key", "from").send(to="a@b.c", subject="s", html="<p>x</p>")


def test_resend_5xx_is_retriable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_service.httpx, "post", lambda *a, **k: _Resp(503))
    with pytest.raises(EmailDeliveryError):
        ResendProvider("key", "from").send(to="a@b.c", subject="s", html="x")


def test_resend_4xx_is_permanent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_service.httpx, "post", lambda *a, **k: _Resp(422))
    with pytest.raises(RuntimeError):
        ResendProvider("key", "from").send(to="a@b.c", subject="s", html="x")


def test_resend_network_error_is_retriable(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*a: object, **k: object) -> None:
        raise httpx.ConnectError("down")

    monkeypatch.setattr(email_service.httpx, "post", _boom)
    with pytest.raises(EmailDeliveryError):
        ResendProvider("key", "from").send(to="a@b.c", subject="s", html="x")
