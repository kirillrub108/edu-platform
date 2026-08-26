"""system_service.maintenance_window: when does the SPA show the banner?

Pure function over settings + `now`, so every case pins both explicitly.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.services.system_service import maintenance_window

pytestmark = pytest.mark.unit

START = datetime(2026, 9, 1, 2, 0, tzinfo=timezone.utc)
END = datetime(2026, 9, 1, 3, 0, tzinfo=timezone.utc)


@pytest.fixture
def window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_START", START)
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_END", END)
    monkeypatch.setattr(settings, "MAINTENANCE_MESSAGE", "Обновляем платформу")
    monkeypatch.setattr(settings, "MAINTENANCE_NOTICE_HOURS", 24)


def test_nothing_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_START", None)
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_END", None)

    assert maintenance_window(START) is None


def test_half_configured_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_START", START)
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_END", None)

    assert maintenance_window(START) is None


@pytest.mark.usefixtures("window")
def test_silent_before_the_notice_period_opens() -> None:
    assert maintenance_window(START - timedelta(hours=25)) is None


@pytest.mark.usefixtures("window")
def test_announced_once_inside_the_notice_period() -> None:
    result = maintenance_window(START - timedelta(hours=23))

    assert result is not None
    assert result.is_active is False
    assert result.start == START
    assert result.end == END
    assert result.message == "Обновляем платформу"


@pytest.mark.usefixtures("window")
def test_notice_period_boundary_is_inclusive() -> None:
    assert maintenance_window(START - timedelta(hours=24)) is not None


@pytest.mark.usefixtures("window")
def test_active_inside_the_window() -> None:
    result = maintenance_window(START + timedelta(minutes=30))

    assert result is not None
    assert result.is_active is True


@pytest.mark.usefixtures("window")
def test_active_at_the_exact_start() -> None:
    result = maintenance_window(START)

    assert result is not None
    assert result.is_active is True


@pytest.mark.usefixtures("window")
def test_silent_once_the_window_has_passed() -> None:
    # A stale window left in .env.prod must stop nagging on its own.
    assert maintenance_window(END) is None
    assert maintenance_window(END + timedelta(days=7)) is None


def test_naive_config_values_are_read_as_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_START", START.replace(tzinfo=None))
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_END", END.replace(tzinfo=None))
    monkeypatch.setattr(settings, "MAINTENANCE_NOTICE_HOURS", 24)

    result = maintenance_window(START + timedelta(minutes=1))

    assert result is not None
    assert result.start == START
    assert result.is_active is True


def test_naive_now_is_read_as_utc(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_START", START)
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_END", END)
    monkeypatch.setattr(settings, "MAINTENANCE_NOTICE_HOURS", 24)

    result = maintenance_window((START + timedelta(minutes=1)).replace(tzinfo=None))

    assert result is not None
    assert result.is_active is True


def test_inverted_window_is_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    # end <= start would otherwise read as permanently active.
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_START", END)
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_END", START)
    monkeypatch.setattr(settings, "MAINTENANCE_NOTICE_HOURS", 24)

    assert maintenance_window(START) is None


def test_zero_notice_hours_announces_only_during_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_START", START)
    monkeypatch.setattr(settings, "MAINTENANCE_WINDOW_END", END)
    monkeypatch.setattr(settings, "MAINTENANCE_NOTICE_HOURS", 0)

    assert maintenance_window(START - timedelta(minutes=1)) is None
    assert maintenance_window(START) is not None


def test_blank_env_value_parses_to_none() -> None:
    # "" in .env.prod must not blow up Settings construction on boot.
    from app.config import Settings

    assert Settings._blank_window_is_none("") is None
    assert Settings._blank_window_is_none("   ") is None
    assert Settings._blank_window_is_none("2026-09-01T02:00:00Z") == "2026-09-01T02:00:00Z"
