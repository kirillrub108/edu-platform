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
from datetime import datetime, timedelta, timezone
from typing import Callable
from urllib.parse import unquote

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.celery_app import celery_app
from app.constants import ATTACHMENT_RETENTION_DAYS_AFTER_GRADED, SOFT_DELETE_PURGE_DAYS
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
