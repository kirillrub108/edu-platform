"""Daily purge of soft-deleted records.

Physically removes User / Course / Lesson rows whose `deleted_at` is older than
SOFT_DELETE_PURGE_DAYS, together with their files in storage. Runs on the
`quiz` queue (served by the celery_quiz worker) and is triggered by Celery beat
(see app/celery_app.py).

Sync-only: like every task here it uses the psycopg2 `SyncSession`, never an
AsyncSession. Because the global soft-delete filter (app/database.py) also
applies to sync sessions, every SELECT in this module opts out with
`.execution_options(include_deleted=True)` so it can actually see the rows it
must delete.
"""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import unquote

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.config import settings
from app.constants import (
    ATTACHMENT_RETENTION_DAYS_AFTER_GRADED,
    CACHE_GC_ENABLED,
    LESSON_VIDEO_GC_ENABLED,
    LESSON_VIDEO_KEEP_UNPUBLISHED,
    LESSON_VIDEO_UNPUBLISHED_TTL_DAYS,
    SLIDES_CACHE_MAX_BYTES,
    SLIDES_CACHE_TTL_DAYS,
    SOFT_DELETE_PURGE_DAYS,
    SUMMARIES_CACHE_MAX_BYTES,
    SUMMARIES_CACHE_TTL_DAYS,
)
from app.models.assignment import Assignment, AssignmentAttachment, AssignmentSubmission
from app.models.course import Course
from app.models.lesson import Lesson, Module
from app.models.lesson_video import LessonVideo
from app.models.slide_text import SlideText
from app.models.user import User
from app.services.storage_service import storage_service
from app.tasks.video_pipeline import SyncSession

logger = structlog.get_logger()

# Commit after this many successful deletions so a crash mid-run still makes
# progress and the transaction stays small.
_COMMIT_BATCH = 100


# ── File cleanup helpers ──────────────────────────────────────────────────────

def _rel_from_url(url: str | None) -> str | None:
    """Extract the storage-relative path from a stored /files/ URL (cover_url,
    video_url are signed absolute URLs). Returns None if not a local file URL."""
    if not url:
        return None
    marker = "/files/"
    idx = url.find(marker)
    if idx == -1:
        return None
    # generate_signed_url percent-encodes the path segment; undo that to get
    # the actual on-disk relative path.
    return unquote(url[idx + len(marker):].split("?", 1)[0])


def _remove_file(rel_path: str | None) -> None:
    """Delete one stored file by relative path. Missing file → warning, never
    an exception (purge must be resilient to already-cleaned-up artifacts)."""
    if not rel_path:
        return
    full = storage_service.get_full_path(rel_path)
    if not os.path.exists(full):
        logger.warning("purge_file_missing", path=full)
        return
    try:
        os.remove(full)
        logger.info("purge_file_removed", path=full)
    except OSError:
        logger.warning("purge_file_remove_failed", path=full, exc_info=True)


def _remove_lesson_dirs(lesson_id) -> None:
    """Remove now-empty per-lesson directories left after file deletion."""
    import shutil

    for sub in (f"videos/{lesson_id}", f"lessons/{lesson_id}"):
        full = storage_service.get_full_path(sub)
        if os.path.isdir(full):
            shutil.rmtree(full, ignore_errors=True)


def _purge_assignment_files(session: Session, lesson: Lesson) -> None:
    """Remove attachment files (and their per-submission dirs) for every
    assignment of the lesson, before the row cascade wipes the DB records."""
    import shutil

    submission_ids = (
        session.execute(
            select(AssignmentSubmission.id)
            .join(Assignment, AssignmentSubmission.assignment_id == Assignment.id)
            .where(Assignment.lesson_id == lesson.id)
            .execution_options(include_deleted=True)
        )
        .scalars()
        .all()
    )
    if not submission_ids:
        return
    paths = (
        session.execute(
            select(AssignmentAttachment.file_path)
            .where(AssignmentAttachment.submission_id.in_(submission_ids))
            .execution_options(include_deleted=True)
        )
        .scalars()
        .all()
    )
    for path in paths:
        _remove_file(path)
    for sid in submission_ids:
        full = storage_service.get_full_path(f"assignments/{sid}")
        if os.path.isdir(full):
            shutil.rmtree(full, ignore_errors=True)


def _purge_lesson_files(session: Session, lesson: Lesson) -> None:
    _remove_file(_rel_from_url(lesson.video_url))
    _remove_file(lesson.pptx_path)
    videos = (
        session.execute(
            select(LessonVideo)
            .where(LessonVideo.lesson_id == lesson.id)
            .execution_options(include_deleted=True)
        )
        .scalars()
        .all()
    )
    for video in videos:
        _remove_file(_rel_from_url(video.video_url))
    slides = (
        session.execute(
            select(SlideText)
            .where(SlideText.lesson_id == lesson.id)
            .execution_options(include_deleted=True)
        )
        .scalars()
        .all()
    )
    for slide in slides:
        _remove_file(slide.image_path)
    _purge_assignment_files(session, lesson)
    _remove_lesson_dirs(lesson.id)


def _purge_course_files(session: Session, course: Course) -> None:
    _remove_file(_rel_from_url(course.cover_url))
    # Gather files for every lesson under the course BEFORE the cascade delete
    # removes the rows. include_deleted: lessons themselves may or may not be
    # soft-deleted, but the whole course is going regardless.
    lessons = (
        session.execute(
            select(Lesson)
            .join(Module, Lesson.module_id == Module.id)
            .where(Module.course_id == course.id)
            .execution_options(include_deleted=True)
        )
        .scalars()
        .all()
    )
    for lesson in lessons:
        _purge_lesson_files(session, lesson)


def _purge_user_files(session: Session, user: User) -> None:
    # Deleting the user cascades to their courses (FK ondelete=CASCADE +
    # relationship cascade), so clean those files first.
    courses = (
        session.execute(
            select(Course)
            .where(Course.owner_id == user.id)
            .execution_options(include_deleted=True)
        )
        .scalars()
        .all()
    )
    for course in courses:
        _purge_course_files(session, course)


# ── Submission-attachment retention ──────────────────────────────────────────

def _purge_expired_submission_attachments(session: Session) -> int:
    """Remove attachment files + rows for submissions graded longer than
    ATTACHMENT_RETENTION_DAYS_AFTER_GRADED ago. The submission (grade, feedback,
    thread) stays; only the stored files and their records go. Idempotent: once a
    row is deleted a re-run finds nothing, and _remove_file tolerates a missing
    file, so cascade-deleted attachments from the soft-delete pass don't error."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=ATTACHMENT_RETENTION_DAYS_AFTER_GRADED
    )
    rows = (
        session.execute(
            select(AssignmentAttachment)
            .join(
                AssignmentSubmission,
                AssignmentAttachment.submission_id == AssignmentSubmission.id,
            )
            .where(
                AssignmentSubmission.graded_at.isnot(None),
                AssignmentSubmission.graded_at < cutoff,
            )
            .execution_options(include_deleted=True)
        )
        .scalars()
        .all()
    )
    removed = 0
    for att in rows:
        try:
            _remove_file(att.file_path)
            session.delete(att)
            session.flush()
            removed += 1
            if removed % _COMMIT_BATCH == 0:
                session.commit()
        except Exception:
            session.rollback()
            logger.warning(
                "purge_attachment_failed",
                id=str(getattr(att, "id", None)),
                exc_info=True,
            )
            continue
    session.commit()
    return removed


# ── Generic purge driver ──────────────────────────────────────────────────────

def _purge_model(
    session: Session,
    model: type,
    cutoff: datetime,
    file_cleanup: Callable[[Session, object], None],
) -> int:
    rows = (
        session.execute(
            select(model)
            .where(model.deleted_at.isnot(None), model.deleted_at < cutoff)
            .execution_options(include_deleted=True)
        )
        .scalars()
        .all()
    )
    purged = 0
    for obj in rows:
        try:
            file_cleanup(session, obj)
            session.delete(obj)
            session.flush()
            purged += 1
            logger.info("purge_record_deleted", type=model.__name__, id=str(obj.id))
            if purged % _COMMIT_BATCH == 0:
                session.commit()
        except Exception:
            session.rollback()
            logger.warning(
                "purge_record_failed",
                type=model.__name__,
                id=str(getattr(obj, "id", None)),
                exc_info=True,
            )
            continue
    session.commit()
    return purged


@celery_app.task(name="purge_soft_deleted", queue="quiz")
def purge_soft_deleted() -> dict:
    structlog.contextvars.clear_contextvars()
    cutoff = datetime.now(timezone.utc) - timedelta(days=SOFT_DELETE_PURGE_DAYS)
    counts: dict[str, int] = {}
    with SyncSession() as session:
        # Order: courses, then standalone lessons, then users. Lessons under an
        # already-purged course are gone via cascade and simply won't reappear.
        counts["courses"] = _purge_model(session, Course, cutoff, _purge_course_files)
        counts["lessons"] = _purge_model(session, Lesson, cutoff, _purge_lesson_files)
        counts["users"] = _purge_model(session, User, cutoff, _purge_user_files)
        # Retention sweep for graded submissions (independent of soft-delete).
        counts["expired_attachments"] = _purge_expired_submission_attachments(session)
    logger.info("purge_soft_deleted_done", **counts)
    return counts


# ── Disk cache GC (reproducible slides_cache / summaries_cache) ────────────────

# A crashed GC run can leave an entry half-renamed with this marker in its name;
# enumeration skips those and clears the orphans on the next pass.
_GC_STAGING_MARKER = ".gc-"


def _entry_size(path: str, is_dir: bool) -> int:
    """Total bytes of one cache entry. Resilient to files vanishing mid-walk (a
    concurrent generation may be writing or a sibling evicting): a disappeared
    file contributes 0 instead of raising."""
    if not is_dir:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


def _atomic_evict(path: str, is_dir: bool) -> None:
    """Remove a cache entry atomically: rename to a sibling staging name, then
    delete. The rename is atomic within the cache's filesystem, so an in-flight
    lookup never sees a half-deleted entry masquerading as a valid hit — it finds
    either the whole entry or nothing (→ clean cache miss, next run re-renders)."""
    staging = f"{path}{_GC_STAGING_MARKER}{uuid.uuid4().hex}"
    os.rename(path, staging)
    if is_dir:
        shutil.rmtree(staging, ignore_errors=True)
    else:
        try:
            os.remove(staging)
        except OSError:
            logger.warning("gc_cache_staging_remove_failed", path=staging, exc_info=True)


def _gc_cache(
    root: str, ttl_days: int, max_bytes: int, *, entry_is_dir: bool
) -> tuple[int, int]:
    """Evict entries from one content-hash cache: first every entry whose mtime
    is older than ttl_days, then — if the cache still exceeds max_bytes — the
    least-recently-used first until it fits. Recency is the mtime we bump on
    every hit (os.utime), so this is a true LRU. Returns (removed, bytes_freed)."""
    if not os.path.isdir(root):
        return 0, 0

    ttl_cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).timestamp()
    entries: list[tuple[str, float, int]] = []  # (path, mtime, size)
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if _GC_STAGING_MARKER in name:
            _atomic_evict(path, entry_is_dir)  # orphan from a crashed run
            continue
        try:
            if os.path.islink(path):
                continue  # never delete through a symlink
            if entry_is_dir and not os.path.isdir(path):
                continue
            if not entry_is_dir and not (os.path.isfile(path) and name.endswith(".txt")):
                continue
            mtime = os.path.getmtime(path)
        except OSError:
            logger.warning("gc_cache_stat_failed", path=path, exc_info=True)
            continue
        entries.append((path, mtime, _entry_size(path, entry_is_dir)))

    removed = 0
    freed = 0

    # ── TTL pass ──
    survivors: list[tuple[str, float, int]] = []
    for entry in entries:
        path, mtime, size = entry
        if mtime < ttl_cutoff:
            try:
                _atomic_evict(path, entry_is_dir)
                removed += 1
                freed += size
            except OSError:
                logger.warning("gc_cache_evict_failed", path=path, exc_info=True)
                survivors.append(entry)
        else:
            survivors.append(entry)

    # ── size-cap pass: oldest mtime first until under the cap ──
    total = sum(size for _p, _m, size in survivors)
    if total > max_bytes:
        for path, _mtime, size in sorted(survivors, key=lambda e: e[1]):
            if total <= max_bytes:
                break
            try:
                _atomic_evict(path, entry_is_dir)
                removed += 1
                freed += size
                total -= size
            except OSError:
                logger.warning("gc_cache_evict_failed", path=path, exc_info=True)

    return removed, freed


@celery_app.task(name="gc_disk_caches", queue="quiz")
def gc_disk_caches() -> dict[str, int]:
    """Daily reclaim of the reproducible slides_cache / summaries_cache. No-op
    when CACHE_GC_ENABLED is false. Both caches are local even under the S3
    backend, so they're addressed directly under STORAGE_PATH."""
    structlog.contextvars.clear_contextvars()
    counts = {
        "slides_removed": 0,
        "slides_bytes": 0,
        "summaries_removed": 0,
        "summaries_bytes": 0,
    }
    if not CACHE_GC_ENABLED:
        logger.info("gc_disk_caches_disabled")
        return counts
    counts["slides_removed"], counts["slides_bytes"] = _gc_cache(
        os.path.join(settings.STORAGE_PATH, "slides_cache"),
        SLIDES_CACHE_TTL_DAYS,
        SLIDES_CACHE_MAX_BYTES,
        entry_is_dir=True,
    )
    counts["summaries_removed"], counts["summaries_bytes"] = _gc_cache(
        os.path.join(settings.STORAGE_PATH, "summaries_cache"),
        SUMMARIES_CACHE_TTL_DAYS,
        SUMMARIES_CACHE_MAX_BYTES,
        entry_is_dir=False,
    )
    logger.info("gc_disk_caches_done", **counts)
    return counts


# ── Stale unpublished LessonVideo GC ──────────────────────────────────────────

def _evict_lesson_video(session: Session, video: LessonVideo) -> None:
    """Delete a video's stored file (via storage_service — S3-safe) then its row.
    File first so a crash between the two steps leaves an orphan file the next
    run retries, never a row pointing at a deleted file. A missing file → warn
    and still delete the row (the "row exists, file gone" case)."""
    rel = storage_service.relative_path_from_url(video.video_url)
    if rel is None:
        logger.warning("gc_video_url_unresolvable", id=str(video.id), url=video.video_url)
    else:
        try:
            if storage_service.exists(rel):
                storage_service.delete_file(rel)
                logger.info("gc_video_file_removed", id=str(video.id), path=rel)
            else:
                logger.warning("gc_video_file_missing", id=str(video.id), path=rel)
        except Exception:
            logger.warning(
                "gc_video_file_remove_failed", id=str(video.id), path=rel, exc_info=True
            )
    session.delete(video)
    session.flush()


def _gc_lesson_videos_session(session: Session) -> int:
    """Prune cold UNPUBLISHED video versions. Per lesson: keep every published
    version, keep the newest KEEP_UNPUBLISHED unpublished, delete the remaining
    unpublished only when older than the TTL. Invariant: a lesson is never left
    with zero videos — with no published version, at least one (newest)
    unpublished always survives regardless of KEEP_UNPUBLISHED. is_published=True
    is NEVER a deletion candidate. Returns rows removed."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=LESSON_VIDEO_UNPUBLISHED_TTL_DAYS)
    lesson_ids = (
        session.execute(
            select(LessonVideo.lesson_id)
            .where(LessonVideo.is_published.is_(False))
            .distinct()
        )
        .scalars()
        .all()
    )
    removed = 0
    for lesson_id in lesson_ids:
        try:
            published = session.scalar(
                select(func.count())
                .select_from(LessonVideo)
                .where(
                    LessonVideo.lesson_id == lesson_id,
                    LessonVideo.is_published.is_(True),
                )
            )
            unpublished = (
                session.execute(
                    select(LessonVideo)
                    .where(
                        LessonVideo.lesson_id == lesson_id,
                        LessonVideo.is_published.is_(False),
                    )
                    .order_by(LessonVideo.created_at.desc())
                )
                .scalars()
                .all()
            )
            # Never orphan the lesson: with no published version, keep ≥1 unpublished.
            keep = LESSON_VIDEO_KEEP_UNPUBLISHED if published else max(LESSON_VIDEO_KEEP_UNPUBLISHED, 1)
            for video in unpublished[keep:]:
                if video.created_at is not None and video.created_at < cutoff:
                    _evict_lesson_video(session, video)
                    removed += 1
            session.commit()
        except Exception:
            session.rollback()
            logger.warning("gc_video_lesson_failed", lesson_id=str(lesson_id), exc_info=True)
            continue
    return removed


@celery_app.task(name="gc_lesson_videos", queue="quiz")
def gc_lesson_videos() -> dict[str, int]:
    """Daily prune of stale unpublished LessonVideo versions. No-op when
    LESSON_VIDEO_GC_ENABLED is false. NEVER touches is_published=True versions."""
    structlog.contextvars.clear_contextvars()
    if not LESSON_VIDEO_GC_ENABLED:
        logger.info("gc_lesson_videos_disabled")
        return {"videos_removed": 0}
    with SyncSession() as session:
        removed = _gc_lesson_videos_session(session)
    logger.info("gc_lesson_videos_done", videos_removed=removed)
    return {"videos_removed": removed}
