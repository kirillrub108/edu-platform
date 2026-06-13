"""Race-safe get-or-create for LessonProgress.

LessonProgress has a UNIQUE constraint on (enrollment_id, lesson_id)
(`uq_lesson_progress_enrollment_lesson`), so two concurrent requests can both
SELECT None and race the INSERT — the loser would otherwise raise an uncaught
IntegrityError (500). The losing INSERT is contained in a SAVEPOINT so its
failure rolls back only that insert, never the caller's outer transaction;
we then re-SELECT the now-committed row. Mirrors the get_or_create_quiz idiom
in quiz_service.
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enrollment import LessonProgress


async def get_or_create_lesson_progress(
    db: AsyncSession, *, enrollment_id: UUID, lesson_id: UUID
) -> LessonProgress:
    progress = await db.scalar(
        select(LessonProgress).where(
            LessonProgress.enrollment_id == enrollment_id,
            LessonProgress.lesson_id == lesson_id,
        )
    )
    if progress is not None:
        return progress

    progress = LessonProgress(enrollment_id=enrollment_id, lesson_id=lesson_id)
    try:
        async with db.begin_nested():
            db.add(progress)
            await db.flush()
        return progress
    except IntegrityError:
        progress = await db.scalar(
            select(LessonProgress).where(
                LessonProgress.enrollment_id == enrollment_id,
                LessonProgress.lesson_id == lesson_id,
            )
        )
        if progress is None:
            raise  # genuine integrity failure, not the (enrollment, lesson) race
        return progress
