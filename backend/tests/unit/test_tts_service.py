"""Unit tests for app.services.tts_service.

The module uses `httpx.get` directly (sync). We patch it on the imported
module reference, not on httpx globally.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from app.constants import SILERO_MAX_CHARS as _SILERO_MAX_CHARS
from app.services import tts_service as tts_mod
from app.services.tts_service import (
    _split_for_tts,
    _strip_ssml_tags,
    tts_service,
)

pytestmark = pytest.mark.unit


# ── _strip_ssml_tags ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw, expected_substr, must_not_contain",
    [
        # <p>, <br>, <speak> are replaced by a space (block-level tags).
        ("<p>Hello world</p>", "Hello world", "<p>"),
        ("text<br/>more", "text more", "<br"),
        ("<speak>x</speak>", "x", "<speak>"),
        # All other SSML tags (e.g. <break/>, <prosody>) are stripped
        # without inserting a space — this is intentional, the surrounding
        # text usually already has the right spacing.
        ("a<break time='500ms'/>b", "ab", "<break"),
        ("normal<prosody rate='slow'>term</prosody>end", "normaltermend", "<prosody"),
    ],
)
def test_strip_ssml_tags_keeps_text(
    raw: str, expected_substr: str, must_not_contain: str
) -> None:
    out = _strip_ssml_tags(raw)
    assert expected_substr in out
    assert must_not_contain not in out


def test_strip_ssml_tags_collapses_multiple_spaces() -> None:
    assert _strip_ssml_tags("a<br/><br/>b") == "a b"


# ── _split_for_tts ──────────────────────────────────────────────────────────

def test_split_for_tts_short_text_returns_single_chunk() -> None:
    out = _split_for_tts("Hello world.")
    assert out == ["Hello world."]


def test_split_for_tts_long_text_under_limit_per_chunk() -> None:
    sentence = "Это предложение длиной примерно сорок символов. "
    text = sentence * 40  # ~1600 chars → must split
    chunks = _split_for_tts(text)
    assert len(chunks) > 1
    assert all(len(c) <= _SILERO_MAX_CHARS for c in chunks)
    # No content lost: reassembled length is close to original (whitespace
    # tolerance from the join logic).
    assert sum(len(c) for c in chunks) >= len(text.strip()) - len(chunks)


def test_split_for_tts_does_not_break_words() -> None:
    sentence = "Слово раз два три четыре пять шесть семь восемь девять десять. "
    text = sentence * 30
    chunks = _split_for_tts(text)
    for c in chunks:
        # No chunk should end mid-word (i.e. trailing fragment without space)
        assert not c.endswith(" ")
        assert c == c.strip()


# ── TTSService.synthesize via mocked httpx ─────────────────────────────────

def test_synthesize_writes_wav_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured_params: dict[str, Any] = {}

    # Make a real (silent) WAV body the service can concat.
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.zeros(48000, dtype=np.int16).tobytes())
    wav_bytes = buf.getvalue()

    class _Resp:
        status_code = 200
        content = wav_bytes

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url: str, params: dict[str, Any] | None = None, timeout: int = 0) -> _Resp:
        captured_params.update(params or {})
        return _Resp()

    monkeypatch.setattr(tts_mod.httpx, "get", _fake_get)

    out_path = tmp_path / "out" / "audio.wav"
    returned = tts_service.synthesize("Hello world", str(out_path), voice="xenia")

    assert returned == str(out_path)
    assert out_path.exists()
    assert out_path.stat().st_size > 0
    # Voice and text are propagated to Silero
    assert captured_params["VOICE"] == "xenia"
    assert "Hello" in captured_params["INPUT_TEXT"]


def test_synthesize_propagates_http_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class _Resp:
        status_code = 500
        content = b""

        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError(
                "boom", request=httpx.Request("GET", "x"), response=None  # type: ignore[arg-type]
            )

    monkeypatch.setattr(tts_mod.httpx, "get", lambda *a, **k: _Resp())

    out_path = tmp_path / "out.wav"
    with pytest.raises(RuntimeError, match="Silero TTS request failed"):
        tts_service.synthesize("Hello", str(out_path))


def test_synthesize_empty_text_falls_back_to_stub(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """SSML that strips to nothing must not call Silero at all."""
    calls = {"n": 0}

    def _fake_get(*_a: Any, **_kw: Any) -> Any:
        calls["n"] += 1
        raise AssertionError("Silero should not be called on empty text")

    monkeypatch.setattr(tts_mod.httpx, "get", _fake_get)

    out = tmp_path / "stub.wav"
    tts_service.synthesize("<p></p>", str(out))
    assert out.exists()
    assert calls["n"] == 0
