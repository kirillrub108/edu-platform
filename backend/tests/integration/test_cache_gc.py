"""Periodic disk GC — cache eviction (TTL + size-cap), recency bumps on cache
HIT, and stale-unpublished LessonVideo pruning.

Cache / recency tests are filesystem-only: they point STORAGE_PATH (or the cache
dir) at a tmp path and monkeypatch the module-bound GC thresholds. LessonVideo
tests use a psycopg2 `sync_session` mirroring the Celery worker, exactly like
tests/integration/test_soft_delete.py (the task opens its own SyncSession).
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.course import Course
from app.models.lesson import ContentType, CreationMode, Lesson, LessonStatus, Module
from app.models.lesson_video import LessonVideo
from app.models.user import User, UserRole
from app.services.auth_service import hash_password

pytestmark = pytest.mark.integration


def _days_ago_ts(days: float) -> float:
    return (datetime.now(timezone.utc) - timedelta(days=days)).timestamp()


# ── Cache-entry fixtures on disk ──────────────────────────────────────────────

def _make_slides_entry(root: Path, key: str, *, age_days: float, size: int = 16) -> Path:
    """One slides_cache entry: a <key>/ dir holding a PNG, with the DIRECTORY
    mtime set to `age_days` ago (recency is the dir mtime the GC evicts by)."""
    entry = root / key
    entry.mkdir(parents=True, exist_ok=True)
    (entry / "slide-1.png").write_bytes(b"x" * size)
    ts = _days_ago_ts(age_days)
    os.utime(entry, (ts, ts))
    return entry


def _make_summary_entry(root: Path, key: str, *, age_days: float, size: int = 16) -> Path:
    """One summaries_cache entry: a <key>.txt file with mtime `age_days` ago."""
    root.mkdir(parents=True, exist_ok=True)
    entry = root / f"{key}.txt"
    entry.write_bytes(b"x" * size)
    ts = _days_ago_ts(age_days)
    os.utime(entry, (ts, ts))
    return entry


# ── Cache GC: TTL + size cap + kill-switch ────────────────────────────────────

def test_cache_ttl_evicts_stale_keeps_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tasks import purge_pipeline

    monkeypatch.setattr("app.tasks.purge_pipeline.settings.STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr("app.tasks.purge_pipeline.SLIDES_CACHE_TTL_DAYS", 30)
    monkeypatch.setattr("app.tasks.purge_pipeline.SLIDES_CACHE_MAX_BYTES", 10**12)  # cap inert

    slides = tmp_path / "slides_cache"
    stale = _make_slides_entry(slides, "stale", age_days=40)
    fresh = _make_slides_entry(slides, "fresh", age_days=1)

    counts = purge_pipeline.gc_disk_caches()

    assert not stale.exists()
    assert fresh.exists()
    assert counts["slides_removed"] == 1


def test_cache_size_cap_evicts_least_recently_used_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tasks import purge_pipeline

    monkeypatch.setattr("app.tasks.purge_pipeline.settings.STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr("app.tasks.purge_pipeline.SLIDES_CACHE_TTL_DAYS", 3650)  # TTL inert
    monkeypatch.setattr("app.tasks.purge_pipeline.SLIDES_CACHE_MAX_BYTES", 20)

    slides = tmp_path / "slides_cache"
    oldest = _make_slides_entry(slides, "oldest", age_days=10, size=16)
    middle = _make_slides_entry(slides, "middle", age_days=5, size=16)
    newest = _make_slides_entry(slides, "newest", age_days=1, size=16)

    counts = purge_pipeline.gc_disk_caches()

    # 48 B > 20 B cap → drop oldest (→32), then middle (→16 ≤ 20) → stop.
    assert not oldest.exists()
    assert not middle.exists()
    assert newest.exists()
    assert counts["slides_removed"] == 2


def test_cache_gc_disabled_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tasks import purge_pipeline

    monkeypatch.setattr("app.tasks.purge_pipeline.settings.STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr("app.tasks.purge_pipeline.CACHE_GC_ENABLED", False)
    monkeypatch.setattr("app.tasks.purge_pipeline.SLIDES_CACHE_TTL_DAYS", 1)

    stale = _make_slides_entry(tmp_path / "slides_cache", "stale", age_days=99)

    counts = purge_pipeline.gc_disk_caches()

    assert stale.exists()
    assert counts == {
        "slides_removed": 0,
        "slides_bytes": 0,
        "summaries_removed": 0,
        "summaries_bytes": 0,
    }


def test_summaries_cache_ttl_evicts_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tasks import purge_pipeline

    monkeypatch.setattr("app.tasks.purge_pipeline.settings.STORAGE_PATH", str(tmp_path))
    monkeypatch.setattr("app.tasks.purge_pipeline.SUMMARIES_CACHE_TTL_DAYS", 60)
    monkeypatch.setattr("app.tasks.purge_pipeline.SUMMARIES_CACHE_MAX_BYTES", 10**12)

    summ = tmp_path / "summaries_cache"
    stale = _make_summary_entry(summ, "a" * 8, age_days=70)
    fresh = _make_summary_entry(summ, "b" * 8, age_days=5)

    counts = purge_pipeline.gc_disk_caches()

    assert not stale.exists()
    assert fresh.exists()
    assert counts["summaries_removed"] == 1


def test_cache_gc_idempotent_on_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tasks import purge_pipeline

    monkeypatch.setattr("app.tasks.purge_pipeline.settings.STORAGE_PATH", str(tmp_path))
    # No cache dirs exist — must not raise and reclaim nothing, twice.
    first = purge_pipeline.gc_disk_caches()
    second = purge_pipeline.gc_disk_caches()
    assert first["slides_removed"] == 0 and first["summaries_removed"] == 0
    assert second["slides_removed"] == 0 and second["summaries_removed"] == 0


# ── Recency bump on cache HIT (both slide branches + summaries read) ───────────

def test_slides_disk_hit_bumps_dir_mtime(tmp_path: Path) -> None:
    from app.services import video_service

    video_service._slides_cache.clear()  # force the on-disk hit path, not memory

    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"fake-pptx-disk-hit")  # disk-hit path only md5s it, never parses
    cache_dir = tmp_path / "cache"
    key = video_service._pptx_cache_key(str(pptx))
    entry = cache_dir / key
    entry.mkdir(parents=True)
    (entry / "slide-1.png").write_bytes(b"png")
    old = _days_ago_ts(10)
    os.utime(entry, (old, old))

    svc = video_service.VideoService()
    result = svc.convert_pptx_to_images(
        str(pptx), str(tmp_path / "out"), cache_dir=str(cache_dir)
    )

    assert [Path(p).name for p in result] == ["slide-1.png"]  # return value unchanged
    assert os.path.getmtime(entry) > old  # recency bumped


def test_slides_memory_hit_also_bumps_dir_mtime(tmp_path: Path) -> None:
    from app.services import video_service

    video_service._slides_cache.clear()

    pptx = tmp_path / "deck.pptx"
    pptx.write_bytes(b"fake-pptx-memory-hit")
    cache_dir = tmp_path / "cache"
    key = video_service._pptx_cache_key(str(pptx))
    entry = cache_dir / key
    entry.mkdir(parents=True)
    (entry / "slide-1.png").write_bytes(b"png")

    svc = video_service.VideoService()
    # First call: disk hit populates the in-memory shadow.
    svc.convert_pptx_to_images(str(pptx), str(tmp_path / "o1"), cache_dir=str(cache_dir))
    # Make the dir look "cold", then call again → served from MEMORY. A warm
    # memory entry must still refresh disk recency, else the GC evicts it.
    old = _days_ago_ts(10)
    os.utime(entry, (old, old))
    svc.convert_pptx_to_images(str(pptx), str(tmp_path / "o2"), cache_dir=str(cache_dir))

    assert os.path.getmtime(entry) > old


def test_summaries_read_bumps_file_mtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import vision_analysis

    monkeypatch.setattr(vision_analysis, "SUMMARY_CACHE_DIR", str(tmp_path))
    key = "deadbeef"
    entry = tmp_path / f"{key}.txt"
    entry.write_text("cached summary", encoding="utf-8")
    old = _days_ago_ts(10)
    os.utime(entry, (old, old))

    # _read_cache uses no instance state — skip __init__ (avoids provider env deps).
    svc = object.__new__(vision_analysis.VisionAnalysisService)
    got = svc._read_cache(key)

    assert got == "cached summary"  # return value unchanged
    assert os.path.getmtime(entry) > old  # recency bumped


# ── LessonVideo GC (sync) ─────────────────────────────────────────────────────

@pytest.fixture()
def sync_session(_alembic_upgraded: None) -> Iterator[Session]:
    """psycopg2 session mirroring the Celery worker; truncates all tables after."""
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    sess = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE "
                    "lesson_progress, enrollments, slide_texts, quiz_questions, "
                    "lesson_videos, lessons, modules, courses, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
            conn.commit()
        engine.dispose()


def _make_lesson(session: Session) -> Lesson:
    user = User(
        email=f"t-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("password123"),
        role=UserRole.teacher,
        is_active=True,
    )
    session.add(user)
    session.commit()
    course = Course(title="c", owner_id=user.id)
    session.add(course)
    session.commit()
    module = Module(title="m", order=0, course_id=course.id)
    session.add(module)
    session.commit()
    lesson = Lesson(
        title="l",
        order=0,
        module_id=module.id,
        content_type=ContentType.video,
        creation_mode=CreationMode.presentation_and_text,
        status=LessonStatus.draft,
    )
    session.add(lesson)
    session.commit()
    return lesson


def _add_video(
    session: Session,
    lesson: Lesson,
    *,
    published: bool,
    age_days: float,
    with_file: bool = True,
) -> tuple[LessonVideo, str | None]:
    """Create a LessonVideo row (created_at = age_days ago) with, optionally, a
    real file on disk. Returns (row, full_path_or_None)."""
    from app.services.storage_service import storage_service

    vid_id = uuid.uuid4()
    rel = f"videos/{lesson.id}/{vid_id.hex}.mp4"
    full: str | None = None
    if with_file:
        full = storage_service.get_full_path(rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as fh:
            fh.write(b"video")
    video = LessonVideo(
        id=vid_id,
        lesson_id=lesson.id,
        video_url=f"http://testserver/files/{rel}",
        voice="xenia",
        creation_mode="presentation_and_text",
        is_published=published,
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
    )
    session.add(video)
    session.commit()
    return video, full


def _remaining_ids(session: Session, lesson_id: uuid.UUID) -> list[uuid.UUID]:
    session.expire_all()
    return (
        session.execute(
            select(LessonVideo.id).where(LessonVideo.lesson_id == lesson_id)
        )
        .scalars()
        .all()
    )


def test_gc_never_deletes_published_even_when_old(sync_session: Session) -> None:
    from app.tasks.purge_pipeline import gc_lesson_videos

    lesson = _make_lesson(sync_session)
    pub, pub_full = _add_video(sync_session, lesson, published=True, age_days=400)
    # A cold unpublished alongside it makes the lesson a GC candidate.
    cold, cold_full = _add_video(sync_session, lesson, published=False, age_days=400)

    result = gc_lesson_videos()

    remaining = _remaining_ids(sync_session, lesson.id)
    assert pub.id in remaining  # published is NEVER a deletion candidate
    assert os.path.exists(pub_full)
    # published counts as "the lesson has a video", so the lone unpublished is
    # eligible; with KEEP=2 it still survives (unpublished[2:] is empty).
    assert cold.id in remaining
    assert result["videos_removed"] == 0


def test_gc_keeps_newest_unpublished_deletes_cold(sync_session: Session) -> None:
    from app.tasks.purge_pipeline import gc_lesson_videos

    lesson = _make_lesson(sync_session)
    v1, f1 = _add_video(sync_session, lesson, published=False, age_days=40)
    v2, f2 = _add_video(sync_session, lesson, published=False, age_days=50)
    v3, f3 = _add_video(sync_session, lesson, published=False, age_days=60)
    v4, f4 = _add_video(sync_session, lesson, published=False, age_days=70)
    # Capture ids before the GC deletes rows (its own session) — reloading a
    # deleted ORM object afterwards raises ObjectDeletedError.
    v1_id, v2_id, v3_id, v4_id = v1.id, v2.id, v3.id, v4.id

    result = gc_lesson_videos()

    remaining = _remaining_ids(sync_session, lesson.id)
    # newest KEEP_UNPUBLISHED (2) survive; the rest, being past TTL, go.
    assert v1_id in remaining and v2_id in remaining
    assert v3_id not in remaining and v4_id not in remaining
    assert os.path.exists(f1) and os.path.exists(f2)
    assert not os.path.exists(f3) and not os.path.exists(f4)
    assert result["videos_removed"] == 2


def test_gc_single_unpublished_past_ttl_survives(sync_session: Session) -> None:
    """A lesson whose ONLY version is unpublished and past TTL must NOT be
    deleted — otherwise the lesson is left with a dangling video_url."""
    from app.tasks.purge_pipeline import gc_lesson_videos

    lesson = _make_lesson(sync_session)
    only, only_full = _add_video(sync_session, lesson, published=False, age_days=400)

    result = gc_lesson_videos()

    remaining = _remaining_ids(sync_session, lesson.id)
    assert only.id in remaining
    assert os.path.exists(only_full)
    assert result["videos_removed"] == 0


def test_gc_never_orphans_lesson_even_with_keep_zero(
    sync_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even with KEEP_UNPUBLISHED=0, a no-published lesson keeps its newest
    unpublished (keep = max(KEEP, 1))."""
    from app.tasks import purge_pipeline

    monkeypatch.setattr("app.tasks.purge_pipeline.LESSON_VIDEO_KEEP_UNPUBLISHED", 0)
    lesson = _make_lesson(sync_session)
    only, only_full = _add_video(sync_session, lesson, published=False, age_days=400)

    result = purge_pipeline.gc_lesson_videos()

    remaining = _remaining_ids(sync_session, lesson.id)
    assert only.id in remaining
    assert os.path.exists(only_full)
    assert result["videos_removed"] == 0


def test_gc_missing_file_still_deletes_row(sync_session: Session) -> None:
    from app.tasks.purge_pipeline import gc_lesson_videos

    lesson = _make_lesson(sync_session)
    keep1, _ = _add_video(sync_session, lesson, published=False, age_days=1)
    keep2, _ = _add_video(sync_session, lesson, published=False, age_days=2)
    cold, cold_full = _add_video(
        sync_session, lesson, published=False, age_days=99, with_file=False
    )
    assert cold_full is None
    keep1_id, keep2_id, cold_id = keep1.id, keep2.id, cold.id

    result = gc_lesson_videos()  # must not raise despite the missing file

    remaining = _remaining_ids(sync_session, lesson.id)
    assert cold_id not in remaining
    assert keep1_id in remaining and keep2_id in remaining
    assert result["videos_removed"] == 1


def test_gc_lesson_videos_idempotent(sync_session: Session) -> None:
    from app.tasks.purge_pipeline import gc_lesson_videos

    lesson = _make_lesson(sync_session)
    _add_video(sync_session, lesson, published=False, age_days=1)
    _add_video(sync_session, lesson, published=False, age_days=2)
    _add_video(sync_session, lesson, published=False, age_days=99)

    assert gc_lesson_videos()["videos_removed"] == 1
    assert gc_lesson_videos()["videos_removed"] == 0  # nothing new, no error


def test_lesson_video_gc_disabled_is_noop(
    sync_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.tasks import purge_pipeline

    monkeypatch.setattr("app.tasks.purge_pipeline.LESSON_VIDEO_GC_ENABLED", False)
    lesson = _make_lesson(sync_session)
    cold, cold_full = _add_video(sync_session, lesson, published=False, age_days=999)

    result = purge_pipeline.gc_lesson_videos()

    remaining = _remaining_ids(sync_session, lesson.id)
    assert cold.id in remaining
    assert os.path.exists(cold_full)
    assert result == {"videos_removed": 0}


# ── Beat / worker wiring ──────────────────────────────────────────────────────

def test_gc_tasks_registered_and_routed_to_quiz() -> None:
    from app.celery_app import celery_app

    # Picked up via include=["app.tasks.purge_pipeline"] → a worker can run them.
    assert "gc_disk_caches" in celery_app.tasks
    assert "gc_lesson_videos" in celery_app.tasks

    beat = celery_app.conf.beat_schedule
    assert beat["gc-disk-caches-daily"]["task"] == "gc_disk_caches"
    assert beat["gc-disk-caches-daily"]["options"]["queue"] == "quiz"
    assert beat["gc-lesson-videos-daily"]["task"] == "gc_lesson_videos"
    assert beat["gc-lesson-videos-daily"]["options"]["queue"] == "quiz"
