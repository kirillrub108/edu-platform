from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enrollment import Enrollment, LessonProgress
from app.models.lesson import Lesson, Module
from app.schemas.gradebook import (
    GradebookCellRead,
    GradebookRead,
    GradebookStudentRow,
)


def compute_effective_score(
    quiz_score: float | None,
    manual_score: float | None,
) -> float | None:
    if manual_score is not None:
        return manual_score
    return quiz_score


def _cell_from_progress(
    lesson: Lesson,
    progress: LessonProgress | None,
) -> GradebookCellRead:
    return GradebookCellRead(
        lesson_id=lesson.id,
        lesson_title=lesson.title,
        content_type=lesson.content_type.value,
        is_completed=progress.is_completed if progress else False,
        quiz_score=progress.quiz_score if progress else None,
        effective_score=compute_effective_score(
            progress.quiz_score if progress else None,
            progress.manual_score if progress else None,
        ),
        manual_score=progress.manual_score if progress else None,
        teacher_comment=progress.teacher_comment if progress else None,
        completed_at=progress.completed_at if progress else None,
        progress_id=progress.id if progress else None,
    )


async def get_gradebook(
    course_id: UUID,
    course_title: str,
    db: AsyncSession,
) -> GradebookRead:
    lesson_rows = await db.scalars(
        select(Lesson)
        .join(Module, Lesson.module_id == Module.id)
        .where(Module.course_id == course_id)
        .order_by(Module.order, Lesson.order)
    )
    lessons = list(lesson_rows.all())

    enrollment_rows = await db.scalars(
        select(Enrollment)
        .where(Enrollment.course_id == course_id)
        .options(
            selectinload(Enrollment.student),
            selectinload(Enrollment.progress),
        )
    )
    enrollments = list(enrollment_rows.all())

    student_rows: list[GradebookStudentRow] = []
    for enrollment in enrollments:
        progress_by_lesson: dict[UUID, LessonProgress] = {
            p.lesson_id: p for p in enrollment.progress
        }
        cells = [
            _cell_from_progress(lesson, progress_by_lesson.get(lesson.id))
            for lesson in lessons
        ]
        student_rows.append(
            GradebookStudentRow(
                student_id=enrollment.student.id,
                student_name=enrollment.student.full_name,
                student_email=enrollment.student.email,
                lessons=cells,
            )
        )

    return GradebookRead(
        course_id=course_id,
        course_title=course_title,
        students=student_rows,
    )


async def patch_progress(
    course_id: UUID,
    progress_id: UUID,
    updates: dict[str, Any],
    db: AsyncSession,
) -> LessonProgress:
    progress = await db.scalar(
        select(LessonProgress)
        .join(Enrollment, LessonProgress.enrollment_id == Enrollment.id)
        .where(
            LessonProgress.id == progress_id,
            Enrollment.course_id == course_id,
        )
    )
    if progress is None:
        raise HTTPException(status_code=404, detail="Progress record not found in this course")

    for key, value in updates.items():
        setattr(progress, key, value)

    await db.commit()
    return progress
