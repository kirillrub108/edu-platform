"""Pre-prod hardening: LessonProgress (enrollment, lesson) uniqueness +
race-safe get-or-create (progress_service)."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import LessonProgress
from app.models.user import User
from app.services.progress_service import get_or_create_lesson_progress
from tests.factories import (
    make_course,
    make_enrollment,
    make_lesson,
    make_lesson_progress,
    make_module,
)

pytestmark = pytest.mark.integration


async def _scaffold(db: AsyncSession, teacher: User, student: User):
    course = await make_course(db, owner=teacher, is_published=True)
    module = await make_module(db, course)
    lesson = await make_lesson(db, module)
    enrollment = await make_enrollment(db, student, course)
    return lesson, enrollment


async def _progress_count(db: AsyncSession, enrollment_id, lesson_id) -> int:
    return await db.scalar(
        select(func.count())
        .select_from(LessonProgress)
        .where(
            LessonProgress.enrollment_id == enrollment_id,
            LessonProgress.lesson_id == lesson_id,
        )
    )


async def test_get_or_create_is_idempotent(
    db_session: AsyncSession, teacher_user: User, student_user: User
) -> None:
    lesson, enrollment = await _scaffold(db_session, teacher_user, student_user)

    first = await get_or_create_lesson_progress(
        db_session, enrollment_id=enrollment.id, lesson_id=lesson.id
    )
    second = await get_or_create_lesson_progress(
        db_session, enrollment_id=enrollment.id, lesson_id=lesson.id
    )

    assert first.id == second.id
    assert await _progress_count(db_session, enrollment.id, lesson.id) == 1


async def test_get_or_create_returns_existing_row(
    db_session: AsyncSession, teacher_user: User, student_user: User
) -> None:
    lesson, enrollment = await _scaffold(db_session, teacher_user, student_user)
    existing = await make_lesson_progress(
        db_session, enrollment, lesson, is_completed=True
    )

    got = await get_or_create_lesson_progress(
        db_session, enrollment_id=enrollment.id, lesson_id=lesson.id
    )

    assert got.id == existing.id
    assert got.is_completed is True


async def test_duplicate_insert_violates_unique_constraint(
    db_session: AsyncSession, teacher_user: User, student_user: User
) -> None:
    lesson, enrollment = await _scaffold(db_session, teacher_user, student_user)
    await make_lesson_progress(db_session, enrollment, lesson)

    # A raw second insert on the same (enrollment, lesson) must hit the DB
    # UNIQUE constraint — never create a second row.
    db_session.add(LessonProgress(enrollment_id=enrollment.id, lesson_id=lesson.id))
    with pytest.raises(IntegrityError):
        await db_session.flush()
    await db_session.rollback()
