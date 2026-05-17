"""Unit tests for app.services.video_service.

We patch subprocess.run (libreoffice / pdftoppm / ffmpeg / ffprobe) so
no external binaries are needed. The cache test exercises the in-process
TTLCache hit-path: the second convert_pptx_to_images call must not run
subprocess again.
"""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from app.services import video_service as vs_mod
from app.services.video_service import VideoService, _trim_trailing_silence

pytestmark = pytest.mark.unit


def _write_wav(path: Path, duration_s: float, trailing_silence_s: float = 0.0) -> None:
    sr = 48000
    tone_n = int(sr * (duration_s - trailing_silence_s))
    silence_n = int(sr * trailing_silence_s)
    t = np.arange(tone_n) / sr
    tone = (np.sin(2 * np.pi * 440 * t) * 32000).astype(np.int16)
    silence = np.zeros(silence_n, dtype=np.int16)
    samples = np.concatenate([tone, silence])
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(samples.tobytes())


# ── _trim_trailing_silence ───────────────────────────────────────────────────
# Patch subprocess to simulate FFmpeg producing the expected output.

@pytest.fixture()
def _patch_silenceremove(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patched ffmpeg silenceremove: writes a shorter WAV than the source."""

    class _Completed:
        def __init__(self, returncode: int = 0, stdout: str = "", stderr: bytes = b"") -> None:
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def _fake_run(cmd: list[str], **_kwargs: Any) -> _Completed:
        if Path(cmd[0]).name == "ffprobe":
            # Source duration is inspected via wave below.
            target = cmd[-1]
            with wave.open(target, "rb") as w:
                duration = w.getnframes() / w.getframerate()
            return _Completed(returncode=0, stdout=f"{duration:.3f}\n")

        if Path(cmd[0]).name == "ffmpeg":
            # silenceremove invocation: write dest as src minus 0.5s
            src = cmd[cmd.index("-i") + 1]
            dest = cmd[-1]
            with wave.open(src, "rb") as w:
                sr = w.getframerate()
                frames = w.readframes(w.getnframes())
            arr = np.frombuffer(frames, dtype=np.int16)
            # Drop the last 0.5s
            keep = max(int(0.1 * sr), len(arr) - int(0.5 * sr))
            arr = arr[:keep]
            with wave.open(dest, "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes(arr.tobytes())
            return _Completed(returncode=0)

        return _Completed(returncode=0)

    monkeypatch.setattr(vs_mod.subprocess, "run", _fake_run)


def test_trim_trailing_silence_shortens_when_silence_present(
    tmp_path: Path, _patch_silenceremove: None
) -> None:
    src = tmp_path / "src.wav"
    dest = tmp_path / "dest.wav"
    _write_wav(src, duration_s=2.0, trailing_silence_s=1.0)

    ok = _trim_trailing_silence(str(src), str(dest))
    assert ok is True
    # Dest must be shorter than source.
    with wave.open(str(src), "rb") as ws, wave.open(str(dest), "rb") as wd:
        src_dur = ws.getnframes() / ws.getframerate()
        dest_dur = wd.getnframes() / wd.getframerate()
    assert dest_dur < src_dur


def test_trim_trailing_silence_returns_false_when_too_short(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    src = tmp_path / "src.wav"
    dest = tmp_path / "dest.wav"
    _write_wav(src, duration_s=0.3)

    class _Completed:
        def __init__(self, rc: int = 0, stdout: str = "") -> None:
            self.returncode = rc
            self.stdout = stdout
            self.stderr = b""

    def _fake_run(cmd: list[str], **_kw: Any) -> _Completed:
        if Path(cmd[0]).name == "ffmpeg":
            # Produce an empty (≈ 0 duration) file
            Path(cmd[-1]).write_bytes(b"")
            return _Completed(0)
        if Path(cmd[0]).name == "ffprobe":
            return _Completed(0, stdout="0.05\n")
        return _Completed(0)

    monkeypatch.setattr(vs_mod.subprocess, "run", _fake_run)
    ok = _trim_trailing_silence(str(src), str(dest))
    assert ok is False


# ── convert_pptx_to_images cache hit ────────────────────────────────────────

def test_convert_pptx_to_images_caches_repeat_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Clear the module-global TTLCache so a previous test doesn't pre-poison.
    with vs_mod._slides_cache_lock:
        vs_mod._slides_cache.clear()

    counter = {"libreoffice": 0, "pdftoppm": 0}

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = b""

    def _fake_run(cmd: list[str], **_kw: Any) -> _Completed:
        prog = Path(cmd[0]).name
        if prog == "libreoffice":
            counter["libreoffice"] += 1
            outdir = cmd[cmd.index("--outdir") + 1]
            Path(outdir).mkdir(parents=True, exist_ok=True)
            src = cmd[-1]
            (Path(outdir) / (Path(src).stem + ".pdf")).write_bytes(b"%PDF-1.4\n%%EOF")
        elif prog == "pdftoppm":
            counter["pdftoppm"] += 1
            prefix = cmd[-1]
            out_dir = Path(prefix).parent
            out_dir.mkdir(parents=True, exist_ok=True)
            for i in (1, 2):
                (out_dir / f"slide-{i}.png").write_bytes(b"\x89PNG\r\n\x1a\n")
        return _Completed()

    monkeypatch.setattr(vs_mod.subprocess, "run", _fake_run)

    pptx = tmp_path / "x.pptx"
    pptx.write_bytes(b"PK\x03\x04 fake pptx content for hashing")

    cache_dir = tmp_path / "cache"
    out_dir_1 = tmp_path / "out1"
    out_dir_2 = tmp_path / "out2"

    svc = VideoService()
    images_1 = svc.convert_pptx_to_images(str(pptx), str(out_dir_1), cache_dir=str(cache_dir))
    images_2 = svc.convert_pptx_to_images(str(pptx), str(out_dir_2), cache_dir=str(cache_dir))

    assert len(images_1) == 2
    assert len(images_2) == 2
    # Second call must NOT invoke either binary
    assert counter["libreoffice"] == 1
    assert counter["pdftoppm"] == 1


# ── concatenate_segments ────────────────────────────────────────────────────

# ── convert_pptx_to_images: disk cache hit ──────────────────────────────────

def test_convert_pptx_to_images_disk_cache_hit_skips_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PNGs already on disk → no subprocess call even with a cold TTLCache."""
    with vs_mod._slides_cache_lock:
        vs_mod._slides_cache.clear()

    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"PK\x03\x04 fake pptx content for hash")

    cache_dir = tmp_path / "cache"
    cache_key = vs_mod._pptx_cache_key(str(pptx))
    cached_subdir = cache_dir / cache_key
    cached_subdir.mkdir(parents=True)
    (cached_subdir / "slide-1.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    call_count: dict[str, int] = {"n": 0}

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = b""

    def _fake_run(cmd: list[str], **_kw: Any) -> _Completed:
        call_count["n"] += 1
        return _Completed()

    monkeypatch.setattr(vs_mod.subprocess, "run", _fake_run)

    svc = VideoService()
    images = svc.convert_pptx_to_images(
        str(pptx), str(tmp_path / "out"), cache_dir=str(cache_dir)
    )

    assert len(images) == 1
    assert call_count["n"] == 0  # no subprocess calls on disk-cache hit


# ── convert_pptx_to_images: libreoffice failure ──────────────────────────────

def test_convert_pptx_to_images_libreoffice_nonzero_exit_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Failed:
        returncode = 1
        stdout = ""
        stderr = b"lo: conversion failed"

    monkeypatch.setattr(vs_mod.subprocess, "run", lambda *a, **kw: _Failed())

    pptx = tmp_path / "bad.pptx"
    pptx.write_bytes(b"PK\x03\x04 fake pptx for fail test")

    with vs_mod._slides_cache_lock:
        vs_mod._slides_cache.clear()

    svc = VideoService()
    with pytest.raises(RuntimeError):
        svc.convert_pptx_to_images(str(pptx), str(tmp_path / "out"))


# ── encode_segment ───────────────────────────────────────────────────────────

def test_encode_segment_calls_ffmpeg_with_still_image_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ffmpeg_calls: list[list[str]] = []

    class _Completed:
        returncode = 0
        stdout = "2.5\n"
        stderr = b""

    def _fake_run(cmd: list[str], **_kw: Any) -> _Completed:
        if Path(cmd[0]).name == "ffmpeg":
            ffmpeg_calls.append(list(cmd))
            out = Path(cmd[-1])
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"MKV")
        return _Completed()

    monkeypatch.setattr(vs_mod.subprocess, "run", _fake_run)

    img = tmp_path / "slide-1.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")
    aud = tmp_path / "slide-1.wav"
    _write_wav(aud, duration_s=2.0)

    svc = VideoService()
    result = svc.encode_segment(0, str(img), str(aud), str(tmp_path))

    assert result.endswith(".mkv")
    encoding_calls = [c for c in ffmpeg_calls if "-loop" in c]
    assert encoding_calls, "Expected an ffmpeg call with -loop (still-image encoding)"
    cmd = encoding_calls[0]
    assert str(img) in cmd
    assert "libx264" in cmd
    assert "stillimage" in cmd  # -tune stillimage


# ── _trim_trailing_silence: ffmpeg failure ───────────────────────────────────

def test_trim_trailing_silence_returns_false_when_ffmpeg_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _Completed:
        def __init__(self, rc: int = 0) -> None:
            self.returncode = rc
            self.stdout = ""
            self.stderr = b""

    def _fake_run(cmd: list[str], **_kw: Any) -> _Completed:
        if Path(cmd[0]).name == "ffmpeg":
            return _Completed(rc=1)
        return _Completed()

    monkeypatch.setattr(vs_mod.subprocess, "run", _fake_run)

    src = tmp_path / "src.wav"
    _write_wav(src, duration_s=1.0)
    dest = tmp_path / "dest.wav"

    ok = _trim_trailing_silence(str(src), str(dest))
    assert ok is False


# ── concatenate_segments ────────────────────────────────────────────────────

def test_concatenate_segments_invokes_ffmpeg_concat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, list[str]] = {}

    class _Completed:
        returncode = 0
        stdout = ""
        stderr = b""

    def _fake_run(cmd: list[str], **_kw: Any) -> _Completed:
        captured["cmd"] = cmd
        # Produce the output file as ffmpeg would.
        Path(cmd[-1]).parent.mkdir(parents=True, exist_ok=True)
        Path(cmd[-1]).write_bytes(b"MP4")
        return _Completed()

    monkeypatch.setattr(vs_mod.subprocess, "run", _fake_run)

    seg1 = tmp_path / "_seg_0000.mkv"
    seg2 = tmp_path / "_seg_0001.mkv"
    seg1.write_bytes(b"x")
    seg2.write_bytes(b"y")

    output = tmp_path / "final.mp4"
    svc = VideoService()
    returned = svc.concatenate_segments([str(seg1), str(seg2)], str(output))

    assert returned == str(output)
    assert output.exists()
    cmd = captured["cmd"]
    assert "-f" in cmd and "concat" in cmd
    # `-safe 0` is required because we pass absolute paths
    assert "-safe" in cmd and "0" in cmd
