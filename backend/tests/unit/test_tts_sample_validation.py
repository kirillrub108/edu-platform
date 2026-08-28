"""Unit tests for the voice/role validation in the /tts/sample endpoint."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.routers import tts as tts_mod

pytestmark = pytest.mark.unit


def test_yandex_accepts_known_voice_and_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod.settings, "TTS_PROVIDER", "yandex")
    tts_mod._validate_voice_role("alena", "neutral")  # must not raise


def test_yandex_rejects_unknown_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod.settings, "TTS_PROVIDER", "yandex")
    with pytest.raises(HTTPException) as exc:
        tts_mod._validate_voice_role("not-a-voice", None)
    assert exc.value.status_code == 422


def test_yandex_rejects_role_unsupported_by_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod.settings, "TTS_PROVIDER", "yandex")
    with pytest.raises(HTTPException):
        tts_mod._validate_voice_role("filipp", "neutral")  # filipp has no roles


def test_polza_accepts_known_voice_without_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod.settings, "TTS_PROVIDER", "polza")
    tts_mod._validate_voice_role("nova", None)  # must not raise


def test_polza_rejects_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod.settings, "TTS_PROVIDER", "polza")
    with pytest.raises(HTTPException):
        tts_mod._validate_voice_role("nova", "neutral")


def test_silero_accepts_only_configured_voice(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod.settings, "TTS_PROVIDER", "silero")
    monkeypatch.setattr(tts_mod.settings, "SILERO_TTS_VOICE", "xenia")
    tts_mod._validate_voice_role("xenia", None)  # must not raise
    with pytest.raises(HTTPException):
        tts_mod._validate_voice_role("other", None)
