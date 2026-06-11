"""Unit tests for TTS disk-cache and checkpoint helpers in video_pipeline.

All tests are pure-unit: no Redis, no Silero, no FFmpeg required.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.tasks.video_pipeline import _cp_delete, _cp_key, _cp_read, _cp_write, _tts_cache_path

pytestmark = pytest.mark.unit


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_redis_mock() -> tuple[MagicMock, dict]:
    """Return (mock, backing_store) where the mock behaves like redis.Redis."""
    store: dict[str, str] = {}
    r = MagicMock()
    r.get.side_effect = lambda key: store.get(key)
    r.set.side_effect = lambda key, val, **kwargs: store.update({key: val})
    r.delete.side_effect = lambda key: store.pop(key, None)
    return r, store


# ── _tts_cache_path ───────────────────────────────────────────────────────────

def test_tts_cache_path_two_level_structure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.tasks.video_pipeline.settings.STORAGE_PATH", str(tmp_path))
    # Pin the provider so the filename suffix is deterministic regardless of the
    # deployment's .env: silero uses the legacy unqualified name.
    monkeypatch.setattr("app.tasks.video_pipeline.settings.TTS_PROVIDER", "silero")
    path = _tts_cache_path("<p>Привет</p>", "xenia")
    assert path is not None
    p = Path(path)
    # storage/tts_cache/<2-char-prefix>/<hash>.<voice>.wav
    assert p.parent.parent.name == "tts_cache"
    assert len(p.parent.name) == 2
    assert p.name.endswith(".xenia.wav")


def test_tts_cache_path_different_voices_produce_different_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.tasks.video_pipeline.settings.STORAGE_PATH", str(tmp_path))
    p1 = _tts_cache_path("<p>text</p>", "xenia")
    p2 = _tts_cache_path("<p>text</p>", "eugene")
    assert p1 != p2


def test_tts_cache_path_different_ssml_produce_different_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.tasks.video_pipeline.settings.STORAGE_PATH", str(tmp_path))
    p1 = _tts_cache_path("<p>slide one</p>", "xenia")
    p2 = _tts_cache_path("<p>slide two</p>", "xenia")
    assert p1 != p2


def test_tts_cache_path_creates_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.tasks.video_pipeline.settings.STORAGE_PATH", str(tmp_path))
    path = _tts_cache_path("<p>hello</p>", "xenia")
    assert path is not None
    assert Path(path).parent.exists()


# ── checkpoint read / write / delete ─────────────────────────────────────────

def test_cp_read_returns_empty_dict_when_key_missing() -> None:
    r, _ = _make_redis_mock()
    assert _cp_read(r, "lesson-123") == {}


def test_cp_write_then_read_round_trips() -> None:
    r, _ = _make_redis_mock()
    data = {
        "voice": "xenia",
        "ssml_chunks": ["<p>hi</p>", "<p>bye</p>"],
        "tts_done": [0],
        "segments_done": [],
    }
    _cp_write(r, "lesson-abc", data)
    assert _cp_read(r, "lesson-abc") == data


def test_cp_write_sets_ttl() -> None:
    r, _ = _make_redis_mock()
    _cp_write(r, "lesson-ttl", {"voice": "xenia"})
    call_kwargs = r.set.call_args
    # ex= argument must be set (7 days = 604800 s)
    assert call_kwargs.kwargs.get("ex") == 86400 * 7


def test_cp_delete_removes_key() -> None:
    r, store = _make_redis_mock()
    store[_cp_key("lesson-xyz")] = json.dumps({"voice": "xenia"})
    _cp_delete(r, "lesson-xyz")
    assert _cp_read(r, "lesson-xyz") == {}


def test_cp_read_swallows_redis_error() -> None:
    r = MagicMock()
    r.get.side_effect = RuntimeError("redis down")
    assert _cp_read(r, "lesson-err") == {}


def test_cp_write_swallows_redis_error() -> None:
    r = MagicMock()
    r.set.side_effect = RuntimeError("redis down")
    # Must not raise
    _cp_write(r, "lesson-err", {"voice": "xenia"})


def test_cp_delete_swallows_redis_error() -> None:
    r = MagicMock()
    r.delete.side_effect = RuntimeError("redis down")
    _cp_delete(r, "lesson-err")


# ── voice-mismatch invalidation (logic only, no Celery) ──────────────────────

def test_checkpoint_voice_mismatch_clears_progress() -> None:
    """If checkpoint voice differs from effective_voice, tts_done/segments_done are cleared."""
    r, _ = _make_redis_mock()
    old_cp = {
        "voice": "xenia",
        "ssml_chunks": ["<p>slide 1</p>"],
        "tts_done": [0],
        "segments_done": [0],
    }
    _cp_write(r, "lesson-v", old_cp)

    cp = _cp_read(r, "lesson-v")
    effective_voice = "eugene"
    voice_matches = cp.get("voice", "") == effective_voice

    if not voice_matches:
        cp["tts_done"] = []
        cp["segments_done"] = []
    cp["voice"] = effective_voice

    assert cp["tts_done"] == []
    assert cp["segments_done"] == []
    # ssml_chunks are preserved
    assert cp["ssml_chunks"] == ["<p>slide 1</p>"]
