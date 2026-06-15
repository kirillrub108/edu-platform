"""Startup reconciliation: lessons stuck in non-terminal status.

Two cases verified:
  1. Stuck lesson (task_id set, updated_at older than grace window) → error + task_id cleared.
  2. Fresh in-flight lesson (task_id set, updated_at recent) → status unchanged.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.course import Course
from app.models.lesson import CreationMode, Lesson, LessonStatus, Module
from app.models.user import User, UserRole
from app.services.auth_service import hash_password

pytestmark = pytest.mark.integration


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


def _make_lesson(
    session: Session,
    status: LessonStatus,
    analyze_task_id: str | None = None,
    video_task_id: str | None = None,
) -> Lesson:
    user = User(
        email=f"t-{uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pw"),
        role=UserRole.teacher,
        is_active=True,
    )
    session.add(user)
    session.commit()
    course = Course(title="C", owner_id=user.id, is_published=False)
    session.add(course)
    session.commit()
    module = Module(title="M", course_id=course.id)
    session.add(module)
    session.commit()
    lesson = Lesson(
        title="L",
        module_id=module.id,
        creation_mode=CreationMode.presentation_and_text,
        status=status,
        analyze_task_id=analyze_task_id,
        video_task_id=video_task_id,
    )
    session.add(lesson)
    session.commit()
    session.refresh(lesson)
    return lesson


def test_stuck_lesson_marked_error(sync_session: Session) -> None:
    """Lesson with analyze_task_id and updated_at past the grace window → error."""
    from app.main import _reconcile_stuck_lessons

    lesson = _make_lesson(
        sync_session,
        status=LessonStatus.analyzing,
        analyze_task_id="celery-task-aaa",
    )
    sync_session.execute(
        text("UPDATE lessons SET updated_at = :ts WHERE id = :id"),
        {"ts": datetime.now(timezone.utc) - timedelta(hours=5), "id": lesson.id},
    )
    sync_session.commit()

    _reconcile_stuck_lessons()

    sync_session.refresh(lesson)
    assert lesson.status == LessonStatus.error
    assert lesson.analyze_task_id is None
    assert lesson.cancel_requested is False


def test_fresh_lesson_untouched(sync_session: Session) -> None:
    """Lesson with video_task_id and recent updated_at (within grace) → unchanged."""
    from app.main import _reconcile_stuck_lessons

    lesson = _make_lesson(
        sync_session,
        status=LessonStatus.processing,
        video_task_id="celery-task-bbb",
    )
    # updated_at is server-default (now) — no manual override needed.

    _reconcile_stuck_lessons()

    sync_session.refresh(lesson)
    assert lesson.status == LessonStatus.processing
    assert lesson.video_task_id == "celery-task-bbb"
