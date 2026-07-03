"""Worker-concurrency budget: CPU-derived pool sizes with env-overrides.

Covers _derive_concurrency (floors/caps + the peak-thread guardrail), the
config.Settings override sanitizer (garbage/0 → auto), and the Silero invariant
(the exported TTS_WORKERS is the value the pool and the container both use)."""

from __future__ import annotations

import pytest

from app import constants
from app.constants import (
    _CORE_CAP,
    _PEAK_MULT,
    _clamp,
    _derive_concurrency,
)

pytestmark = pytest.mark.unit


def _settings(**overrides: object):
    # _env_file=None so a stray .env isn't read; DATABASE_URL comes from the
    # test env. Only the concurrency overrides matter here.
    from app.config import Settings

    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


# ── floors, caps and the peak guardrail ──────────────────────────────────────


@pytest.mark.parametrize("cores", [1, 2, 4, 8, 16, 64])
def test_floors_hold_at_every_core_count(cores: int) -> None:
    d = _derive_concurrency(cores)
    assert d["TTS_WORKERS"] >= 2
    assert d["ENCODE_WORKERS"] >= 1
    assert d["VIDEO_CONCURRENCY"] >= 1
    assert d["VISION_SUMMARY_CONCURRENCY"] >= 1


@pytest.mark.parametrize("cores", [1, 2, 4, 8, 16, 64])
def test_caps_hold_at_every_core_count(cores: int) -> None:
    d = _derive_concurrency(cores)
    assert d["TTS_WORKERS"] <= 6
    assert d["ENCODE_WORKERS"] <= 4
    assert d["VISION_SUMMARY_CONCURRENCY"] <= 6
    assert d["VIDEO_CONCURRENCY"] <= 3


def test_four_cores_matches_historical_defaults() -> None:
    # No sharp UX change on a typical 4-core host: the old hard-coded 4/3/4/1.
    d = _derive_concurrency(4)
    assert d["TTS_WORKERS"] == 4
    assert d["ENCODE_WORKERS"] == 3
    assert d["VISION_SUMMARY_CONCURRENCY"] == 4
    assert d["VIDEO_CONCURRENCY"] == 1


def test_two_cores_shrinks_but_not_below_floors() -> None:
    d = _derive_concurrency(2)
    assert d["VIDEO_CONCURRENCY"] == 1
    assert d["TTS_WORKERS"] == 2
    assert d["ENCODE_WORKERS"] == 1


def test_scales_up_on_big_hosts() -> None:
    assert _derive_concurrency(8)["VIDEO_CONCURRENCY"] == 2
    assert _derive_concurrency(12)["VIDEO_CONCURRENCY"] == 3
    assert _derive_concurrency(8)["TTS_WORKERS"] > _derive_concurrency(2)["TTS_WORKERS"]


def test_core_cap_flattens_huge_hosts() -> None:
    # Beyond _CORE_CAP the result is identical — no runaway thread counts.
    assert _derive_concurrency(_CORE_CAP) == _derive_concurrency(256)


@pytest.mark.parametrize("cores", range(1, _CORE_CAP + 1))
def test_peak_threads_within_multiplier(cores: int) -> None:
    # Peak = VIDEO_CONCURRENCY * (TTS + ENCODE) must stay <= _PEAK_MULT * cores
    # at every core count, so a small host never oversubscribes past the budget.
    d = _derive_concurrency(cores)
    peak = d["VIDEO_CONCURRENCY"] * (d["TTS_WORKERS"] + d["ENCODE_WORKERS"])
    assert peak <= _PEAK_MULT * _clamp(cores, 1, _CORE_CAP)


def test_zero_or_none_cores_fall_back_to_floor() -> None:
    d = _derive_concurrency(0)
    assert d["VIDEO_CONCURRENCY"] == 1
    assert d["TTS_WORKERS"] == 2


# ── env-override sanitizer (config.Settings) ─────────────────────────────────


def test_valid_override_is_parsed() -> None:
    assert _settings(TTS_WORKERS="6").TTS_WORKERS == 6
    assert _settings(VIDEO_CONCURRENCY=3).VIDEO_CONCURRENCY == 3


@pytest.mark.parametrize("bad", ["", "  ", "abc", "0", "-1", "3.5"])
def test_blank_or_garbage_override_falls_back_to_auto(bad: str) -> None:
    # None means "auto" downstream; a typo must not crash boot.
    assert _settings(TTS_WORKERS=bad).TTS_WORKERS is None


def test_unset_override_is_none() -> None:
    assert _settings().TTS_WORKERS is None
    assert _settings().CPU_BUDGET is None


# ── override wins over the derived value ─────────────────────────────────────


def test_override_takes_precedence_over_derivation(monkeypatch: pytest.MonkeyPatch) -> None:
    # Re-run the module's selection logic with a pinned override and a divergent
    # auto value: the override must win verbatim (manual mode, not re-clamped).
    monkeypatch.setattr(constants.settings, "TTS_WORKERS", 5, raising=False)
    resolved = constants.settings.TTS_WORKERS or _derive_concurrency(4)["TTS_WORKERS"]
    assert resolved == 5

    monkeypatch.setattr(constants.settings, "TTS_WORKERS", None, raising=False)
    resolved_auto = constants.settings.TTS_WORKERS or _derive_concurrency(4)["TTS_WORKERS"]
    assert resolved_auto == 4


# ── Silero invariant: one number for pool and container ──────────────────────


def test_exported_tts_workers_is_the_silero_thread_count() -> None:
    # constants.TTS_WORKERS is what the pool uses AND what compose passes to
    # Silero as NUMBER_OF_THREADS (${TTS_WORKERS}); they are the same integer.
    assert isinstance(constants.TTS_WORKERS, int)
    assert constants.TTS_WORKERS >= 2
    expected = constants.settings.TTS_WORKERS or constants._AUTO["TTS_WORKERS"]
    assert constants.TTS_WORKERS == expected
