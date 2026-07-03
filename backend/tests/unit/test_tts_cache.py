"""Unit tests for the chunk-level TTS disk cache in app.services.tts_service."""

from __future__ import annotations

import base64
import io
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.services import tts_service as tts_mod
from app.services.tts_service import (
    _chunk_cache_key,
    _chunk_cache_path,
    _read_chunk_cache,
    _write_chunk_cache,
    tts_service,
)

pytestmark = pytest.mark.unit


def _silent_wav_bytes(nframes: int = 4800) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(48000)
        w.writeframes(np.zeros(nframes, dtype=np.int16).tobytes())
    return buf.getvalue()


# ── _chunk_cache_key ─────────────────────────────────────────────────────────

def test_chunk_cache_key_stable_for_identical_input() -> None:
    key1 = _chunk_cache_key("hello world", "silero", "xenia", "", None)
    key2 = _chunk_cache_key("hello world", "silero", "xenia", "", None)
    assert key1 == key2


@pytest.mark.parametrize(
    "other",
    [
        ("hello world", "silero", "baya", "", None),           # voice changes
        ("hello world", "polza", "xenia", "", None),           # provider changes
        ("hello world", "silero", "xenia", "tts-2", None),     # model changes
        ("hello world", "silero", "xenia", "", 1.2),           # speed changes
        ("different text", "silero", "xenia", "", None),       # text changes
    ],
)
def test_chunk_cache_key_differs_on_any_param_change(other: tuple) -> None:
    base = _chunk_cache_key("hello world", "silero", "xenia", "", None)
    assert _chunk_cache_key(*other) != base


# ── read/write helpers ───────────────────────────────────────────────────────

def test_write_then_read_chunk_cache_roundtrip(tmp_path: Path) -> None:
    key = _chunk_cache_key("some chunk", "silero", "xenia", "", None)
    path = _chunk_cache_path_under(tmp_path, key)
    data = _silent_wav_bytes()

    _write_chunk_cache(path, data)

    assert _read_chunk_cache(path) == data


def test_read_missing_cache_returns_none(tmp_path: Path) -> None:
    key = _chunk_cache_key("never written", "silero", "xenia", "", None)
    path = _chunk_cache_path_under(tmp_path, key)
    assert _read_chunk_cache(path) is None


def test_read_corrupted_empty_cache_returns_none(tmp_path: Path) -> None:
    key = _chunk_cache_key("corrupt me", "silero", "xenia", "", None)
    path = Path(_chunk_cache_path_under(tmp_path, key))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"")  # simulate a crash mid-write leaving a zero-byte file

    assert _read_chunk_cache(str(path)) is None


def _chunk_cache_path_under(root: Path, key: str) -> str:
    p = root / key[:2] / f"{key}.wav"
    return str(p)


# ── end-to-end via tts_service.synthesize (Silero) ──────────────────────────

def test_synthesize_second_call_hits_cache_not_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tts_mod.settings, "STORAGE_PATH", str(tmp_path / "storage"))
    wav_bytes = _silent_wav_bytes()
    calls = {"n": 0}

    class _Resp:
        status_code = 200
        content = wav_bytes

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url: str, params: dict[str, Any] | None = None, timeout: int = 0) -> _Resp:
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(tts_mod.httpx, "get", _fake_get)

    tts_service.synthesize("Hello world", str(tmp_path / "out1.wav"), voice="xenia")
    assert calls["n"] == 1

    tts_service.synthesize("Hello world", str(tmp_path / "out2.wav"), voice="xenia")
    assert calls["n"] == 1  # second call served entirely from cache

    assert (tmp_path / "out2.wav").stat().st_size > 0


def test_synthesize_corrupted_cache_file_resynthesizes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tts_mod.settings, "STORAGE_PATH", str(tmp_path / "storage"))
    wav_bytes = _silent_wav_bytes()
    calls = {"n": 0}

    class _Resp:
        status_code = 200
        content = wav_bytes

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url: str, params: dict[str, Any] | None = None, timeout: int = 0) -> _Resp:
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(tts_mod.httpx, "get", _fake_get)

    key = _chunk_cache_key("Hello world", "silero", "xenia", "", None)
    cache_path = Path(
        tts_mod.settings.STORAGE_PATH, tts_mod.TTS_CHUNK_CACHE_DIR_NAME, key[:2], f"{key}.wav"
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(b"")  # zero-byte cache file, as if a write crashed

    tts_service.synthesize("Hello world", str(tmp_path / "out.wav"), voice="xenia")

    assert calls["n"] == 1  # corrupted cache is ignored, synthesis still happens
    assert cache_path.stat().st_size > 0  # and the cache is repopulated


def test_synthesize_cache_disabled_always_hits_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tts_mod.settings, "STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(tts_mod, "TTS_CHUNK_CACHE_ENABLED", False)
    wav_bytes = _silent_wav_bytes()
    calls = {"n": 0}

    class _Resp:
        status_code = 200
        content = wav_bytes

        def raise_for_status(self) -> None:
            return None

    def _fake_get(url: str, params: dict[str, Any] | None = None, timeout: int = 0) -> _Resp:
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr(tts_mod.httpx, "get", _fake_get)

    tts_service.synthesize("Hello world", str(tmp_path / "out1.wav"), voice="xenia")
    tts_service.synthesize("Hello world", str(tmp_path / "out2.wav"), voice="xenia")

    assert calls["n"] == 2  # no caching → every call hits the network


# ── end-to-end via tts_service.synthesize (Polza) ───────────────────────────

_FAKE_MP3 = b"\xff\xfbFAKE_MP3_PAYLOAD"


def _install_fake_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Result:
        returncode = 0
        stderr = b""

    def _fake_run(cmd: list[str], input: bytes | None = None, capture_output: bool = False, timeout: int = 0) -> _Result:
        with wave.open(cmd[-1], "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(48000)
            w.writeframes(np.zeros(4800, dtype=np.int16).tobytes())
        return _Result()

    monkeypatch.setattr(tts_mod.subprocess, "run", _fake_run)


class _PolzaResp:
    def __init__(self, payload: object) -> None:
        self.status_code = 200
        self._payload = payload
        self.text = ""

    def json(self) -> object:
        return self._payload


def test_polza_second_call_hits_cache_not_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tts_mod.settings, "STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(tts_mod.settings, "TTS_PROVIDER", "polza")
    monkeypatch.setattr(tts_mod.settings, "POLZA_API_KEY", "test-key")
    monkeypatch.setattr(tts_mod.settings, "POLZA_TTS_MODEL", "openai/tts-1")
    _install_fake_ffmpeg(monkeypatch)
    calls = {"n": 0}

    def _fake_post(url: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float = 0) -> _PolzaResp:
        calls["n"] += 1
        return _PolzaResp({"audio": base64.b64encode(_FAKE_MP3).decode()})

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)

    tts_service.synthesize("Привет мир", str(tmp_path / "out1.wav"), voice="nova")
    assert calls["n"] == 1

    tts_service.synthesize("Привет мир", str(tmp_path / "out2.wav"), voice="nova")
    assert calls["n"] == 1  # cache hit skips both HTTP request and ffmpeg transcode


def test_polza_different_voice_is_not_a_cache_hit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(tts_mod.settings, "STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(tts_mod.settings, "TTS_PROVIDER", "polza")
    monkeypatch.setattr(tts_mod.settings, "POLZA_API_KEY", "test-key")
    monkeypatch.setattr(tts_mod.settings, "POLZA_TTS_MODEL", "openai/tts-1")
    _install_fake_ffmpeg(monkeypatch)
    calls = {"n": 0}

    def _fake_post(url: str, json: dict[str, Any] | None = None, headers: dict[str, str] | None = None, timeout: float = 0) -> _PolzaResp:
        calls["n"] += 1
        return _PolzaResp({"audio": base64.b64encode(_FAKE_MP3).decode()})

    monkeypatch.setattr(tts_mod.httpx, "post", _fake_post)

    tts_service.synthesize("Привет мир", str(tmp_path / "out1.wav"), voice="nova")
    tts_service.synthesize("Привет мир", str(tmp_path / "out2.wav"), voice="alloy")

    assert calls["n"] == 2  # different voice → different cache key → no collision
