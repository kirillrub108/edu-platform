"""Public system status: is a maintenance window announced, and is it open now?

Backs GET /api/v1/system/status, which the SPA polls to decide whether to show
the header banner. Configuration-driven (MAINTENANCE_* in .env.prod) — there is
no table and no admin UI, because a planned window is edited by whoever runs the
deploy. See docs/DECISIONS.md §53.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import settings


def _as_utc(value: datetime) -> datetime:
    """Treat a naive .env value as UTC rather than as the container's local time."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class MaintenanceWindow:
    """A configured window, normalised to UTC and evaluated against `now`."""

    __slots__ = ("start", "end", "message", "is_active")

    def __init__(self, start: datetime, end: datetime, message: str, is_active: bool) -> None:
        self.start = start
        self.end = end
        self.message = message
        self.is_active = is_active


def maintenance_window(now: datetime | None = None) -> MaintenanceWindow | None:
    """The window to show the user right now, or None when there is nothing to say.

    Returned once `now` reaches MAINTENANCE_NOTICE_HOURS before the start, and
    dropped once the end passes — so a stale window left in .env.prod stops
    nagging on its own instead of pinning the banner forever.
    """
    start_raw = settings.MAINTENANCE_WINDOW_START
    end_raw = settings.MAINTENANCE_WINDOW_END
    if start_raw is None or end_raw is None:
        return None

    start = _as_utc(start_raw)
    end = _as_utc(end_raw)
    if end <= start:
        # A misconfigured window would otherwise be permanently "active".
        return None

    current = _as_utc(now) if now is not None else datetime.now(timezone.utc)
    notice_from = start - timedelta(hours=max(settings.MAINTENANCE_NOTICE_HOURS, 0))
    if current < notice_from or current >= end:
        return None

    return MaintenanceWindow(
        start=start,
        end=end,
        message=settings.MAINTENANCE_MESSAGE,
        is_active=start <= current < end,
    )
