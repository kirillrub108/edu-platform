"""Unit tests for app.services.tts_service.

The module uses `httpx.get` / `httpx.post` directly (sync). We patch them on
the imported module reference, not on httpx globally.
"""

from __future__ import annotations

import base64
import io
import wave
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from app.constants import POLZA_TTS_MAX_RETRIES as _POLZA_TTS_MAX_RETRIES
from app.constants import SILERO_MAX_CHARS as _SILERO_MAX_CHARS
from app.services import tts_service as tts_mod
from app.services.tts_service import (
    _split_for_tts,
    _strip_ssml_tags,
    strip_tts_artifacts,
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


# ── strip_tts_artifacts: CJK leakage ────────────────────────────────────────

@pytest.mark.parametrize(
    "contaminated, clean",
    [
        # Real production sample: qwen leaked an ideograph pair mid-sentence.
        (
            "а справа мы должны产出 (выдать) уникальный продукт",
            "а справа мы должны (выдать) уникальный продукт",
        ),
        ("слово ひらがな тут", "слово тут"),          # Hiragana
        ("слово カタカナ тут", "слово тут"),          # Katakana
        ("слово 한글 тут", "слово тут"),              # Hangul
        ("конец фразы。 Дальше", "конец фразы Дальше"),  # CJK punctuation
    ],
)
def test_strip_tts_artifacts_removes_cjk(contaminated: str, clean: str) -> None:
    """CJK runs become a single space and doubled spaces are collapsed inside
    strip_tts_artifacts itself — the polza branch has no extra collapse step."""
    assert strip_tts_artifacts(contaminated) == clean


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


def test_synthesize_sanitizes_silero_breaking_chars(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Raw & and stray < must never reach Silero: its process_ssml rejects them
    in ANY form (even &amp;/&lt; entities) with "Invalid XML format" → 500."""
    captured_params: dict[str, Any] = {}

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.zeros(4800, dtype=np.int16).tobytes())
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

    tts_service.synthesize(
        "Упор на R&D, температура < 5 градусов", str(tmp_path / "out.wav")
    )

    sent = captured_params["INPUT_TEXT"]
    assert "&" not in sent
    assert "<" not in sent
    assert "R D" in sent  # replaced with a single space, words preserved
    assert "температура 5 градусов" in sent


def test_synthesize_strips_cjk_characters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """LLM (qwen) occasionally leaks CJK ideographs into Russian narration —
    Silero 500s on them ("Invalid XML format"), polza tries to pronounce them."""
    captured_params: dict[str, Any] = {}

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.zeros(4800, dtype=np.int16).tobytes())
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

    tts_service.synthesize(
        "а справа мы должны产出 (выдать) уникальный продукт テスト 한글",
        str(tmp_path / "out.wav"),
    )

    sent = captured_params["INPUT_TEXT"]
    for leaked in ("产", "出", "テ", "ス", "ト", "한", "글"):
        assert leaked not in sent
    assert "а справа мы должны (выдать) уникальный продукт" in sent
    assert "  " not in sent


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


# ── Polza provider ──────────────────────────────────────────────────────────

_FAKE_MP3 = b"\xff\xfbFAKE_MP3_PAYLOAD"


@pytest.fixture()
def polza_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tts_mod.settings, "TTS_PROVIDER", "polza")
    monkeypatch.setattr(tts_mod.settings, "POLZA_API_KEY", "test-key")
    # Pin the model family: tests must not depend on the deployment's .env value.
    monkeypatch.setattr(
        tts_mod.settings, "POLZA_TTS_MODEL", "elevenlabs/text-to-speech-turbo-2-5"
    )


def _install_fake_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace subprocess.run so the 'transcode' writes a real silent WAV."""
    calls: list[dict[str, Any]] = []

    class _Result:
        returncode = 0
        stderr = b""

    def _fake_run(
        cmd: list[str],
        input: bytes | None = None,
        capture_output: bool = False,
        timeout: int = 0,
    ) -> _Result:
        calls.append({"cmd": cmd, "input": input})
        with wave.open(cmd[-1], "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(np.zeros(4800, dtype=np.int16).tobytes())
        return _Result()

    monkeypatch.setattr(tts_mod.subprocess, "run", _fake_run)
    return calls


class _PolzaResp:
    def __init__(self, status_code: int = 200, payload: object = None, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def test_polza_synthesize_base64_success(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ffmpeg_calls = _install_fake_ffmpeg(monkeypatch)
    captured: dict[str, Any] = {}

    def _fake_post(
        url: str,
        json: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 0,
    ) -> _PolzaResp:
        captured.update({"url": url, "json": json, "headers": headers})
        return _PolzaResp(
            payload={
                "audio": base64.b64encode(_FAKE_MP3).decode(),
                "contentType": "audio/mpeg",
            }
        )

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)

    out_path = tmp_path / "out" / "audio.wav"
    returned = tts_service.synthesize("Привет мир", str(out_path), voice="xenia")

    assert returned == str(out_path)
    assert out_path.exists()
    assert out_path.stat().st_size > 0
    assert captured["url"].endswith("/audio/speech")
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["json"]["model"] == tts_mod.settings.POLZA_TTS_MODEL
    # Frontend (Silero) voice name is mapped to an ElevenLabs voice name.
    assert captured["json"]["voice"] == "Sarah"
    assert "Привет" in captured["json"]["input"]
    # The decoded mp3 reached ffmpeg, with the 48 kHz mono WAV contract.
    assert ffmpeg_calls[0]["input"] == _FAKE_MP3
    cmd = ffmpeg_calls[0]["cmd"]
    assert "48000" in cmd and "-ac" in cmd


def test_polza_synthesize_cdn_url_variant(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_ffmpeg(monkeypatch)
    cdn_url = "https://cdn.polza.ai/audio/abc.mp3"
    downloaded: dict[str, str] = {}

    monkeypatch.setattr(
        tts_mod.httpx,
        "post",
        lambda *a, **k: _PolzaResp(payload={"audio": cdn_url}),
    )

    class _DlResp:
        content = _FAKE_MP3

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url: str, timeout: float = 0) -> _DlResp:
        downloaded["url"] = url
        return _DlResp()

    monkeypatch.setattr(tts_mod.httpx, "get", _fake_get)

    out_path = tmp_path / "audio.wav"
    tts_service.synthesize("Привет", str(out_path))

    assert downloaded["url"] == cdn_url
    assert out_path.exists()


def test_polza_4xx_fails_fast(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = {"n": 0}

    def _fake_post(*_a: Any, **_kw: Any) -> _PolzaResp:
        calls["n"] += 1
        return _PolzaResp(status_code=401, text="invalid token")

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)

    with pytest.raises(RuntimeError, match="Polza TTS request failed"):
        tts_service.synthesize("Привет", str(tmp_path / "out.wav"))
    assert calls["n"] == 1  # 4xx must not be retried


def test_polza_5xx_retries_then_fails(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls = {"n": 0}

    def _fake_post(*_a: Any, **_kw: Any) -> _PolzaResp:
        calls["n"] += 1
        return _PolzaResp(status_code=500, text="upstream error")

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)
    monkeypatch.setattr(tts_mod.time, "sleep", lambda _s: None)

    with pytest.raises(RuntimeError, match="Polza TTS request failed"):
        tts_service.synthesize("Привет", str(tmp_path / "out.wav"))
    assert calls["n"] == _POLZA_TTS_MAX_RETRIES + 1


def test_polza_empty_audio_raises(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        tts_mod.httpx, "post", lambda *a, **k: _PolzaResp(payload={"audio": ""})
    )

    with pytest.raises(RuntimeError, match="Polza TTS returned no audio"):
        tts_service.synthesize("Привет", str(tmp_path / "out.wav"))


def test_polza_missing_api_key_raises_before_http(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tts_mod.settings, "POLZA_API_KEY", "")

    def _fake_post(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("polza must not be called without an API key")

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)

    with pytest.raises(RuntimeError, match="POLZA_API_KEY"):
        tts_service.synthesize("Привет", str(tmp_path / "out.wav"))


def test_polza_unknown_voice_uses_default(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_ffmpeg(monkeypatch)
    captured: dict[str, Any] = {}

    def _fake_post(
        url: str,
        json: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 0,
    ) -> _PolzaResp:
        captured.update(json or {})
        return _PolzaResp(payload={"audio": base64.b64encode(_FAKE_MP3).decode()})

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)

    tts_service.synthesize("Привет", str(tmp_path / "out.wav"), voice="nonexistent")
    assert captured["voice"] == tts_mod.settings.POLZA_DEFAULT_VOICE


def test_polza_voice_tuning_forwarded_when_set(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_ffmpeg(monkeypatch)
    monkeypatch.setattr(tts_mod.settings, "POLZA_TTS_SPEED", 1.1)
    monkeypatch.setattr(tts_mod.settings, "POLZA_TTS_STABILITY", 0.7)
    monkeypatch.setattr(tts_mod.settings, "POLZA_TTS_SIMILARITY", 0.6)
    monkeypatch.setattr(tts_mod.settings, "POLZA_TTS_STYLE", 0.3)
    captured: dict[str, Any] = {}

    def _fake_post(
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 0,
    ) -> _PolzaResp:
        captured.update(json or {})
        return _PolzaResp(payload={"audio": base64.b64encode(_FAKE_MP3).decode()})

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)

    tts_service.synthesize("Привет", str(tmp_path / "out.wav"))
    assert captured["speed"] == 1.1
    assert captured["stability"] == 0.7
    assert captured["similarity_boost"] == 0.6
    assert captured["style"] == 0.3


def test_polza_voice_tuning_absent_by_default(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unset tuning params must not appear in the request body at all."""
    _install_fake_ffmpeg(monkeypatch)
    captured: dict[str, Any] = {}

    def _fake_post(
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 0,
    ) -> _PolzaResp:
        captured.update(json or {})
        return _PolzaResp(payload={"audio": base64.b64encode(_FAKE_MP3).decode()})

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)

    tts_service.synthesize("Привет", str(tmp_path / "out.wav"))
    for param in ("speed", "stability", "similarity_boost", "style"):
        assert param not in captured


def test_polza_openai_model_uses_openai_voice_catalog(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """openai/* models reject ElevenLabs voice names and ElevenLabs-only params
    (language_code, stability, …) with 400 — none of them may be sent."""
    _install_fake_ffmpeg(monkeypatch)
    monkeypatch.setattr(tts_mod.settings, "POLZA_TTS_MODEL", "openai/gpt-4o-mini-tts")
    monkeypatch.setattr(tts_mod.settings, "POLZA_TTS_STABILITY", 0.7)
    captured: dict[str, Any] = {}

    def _fake_post(
        url: str,
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 0,
    ) -> _PolzaResp:
        captured.update(json or {})
        return _PolzaResp(payload={"audio": base64.b64encode(_FAKE_MP3).decode()})

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)

    tts_service.synthesize("Привет", str(tmp_path / "out.wav"), voice="xenia")
    assert captured["voice"] == "nova"  # not the ElevenLabs "Sarah"
    for param in ("language_code", "stability", "speed", "similarity_boost", "style"):
        assert param not in captured

    # Unknown frontend voice falls back to the OpenAI default, not Rachel.
    captured.clear()
    tts_service.synthesize("Привет", str(tmp_path / "out2.wav"), voice="nonexistent")
    assert captured["voice"] == "alloy"


def test_polza_long_text_chunks_and_concats(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_fake_ffmpeg(monkeypatch)
    monkeypatch.setattr(tts_mod, "POLZA_MAX_CHARS", 60)
    inputs: list[str] = []

    def _fake_post(
        url: str,
        json: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float = 0,
    ) -> _PolzaResp:
        inputs.append((json or {})["input"])
        return _PolzaResp(payload={"audio": base64.b64encode(_FAKE_MP3).decode()})

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)

    text = "Это первое предложение. " * 10  # ~240 chars → must split at 60
    out_path = tmp_path / "long.wav"
    tts_service.synthesize(text, str(out_path))

    assert len(inputs) > 1
    assert all(len(i) <= 60 for i in inputs)
    # Chunks were concatenated into one valid WAV.
    with wave.open(str(out_path), "rb") as w:
        assert w.getnframes() == 4800 * len(inputs)


def test_polza_empty_text_falls_back_to_stub(
    polza_provider: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def _fake_post(*_a: Any, **_kw: Any) -> Any:
        raise AssertionError("polza must not be called on empty text")

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)

    out = tmp_path / "stub.wav"
    tts_service.synthesize("<p></p>", str(out))
    assert out.exists()
