from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_teacher
from app.models.course import Course
from app.models.lesson import Lesson
from app.models.user import User
from app.schemas.gradebook import GradebookCellRead, GradebookRead, ProgressUpdate
from app.services import gradebook_service

router = APIRouter(prefix="/api/v1/courses", tags=["gradebook"])


async def _get_owned_course(course_id: UUID, owner: User, db: AsyncSession) -> Course:
    course = await db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    if course.owner_id != owner.id:
        raise HTTPException(status_code=403, detail="Not your course")
    return course


@router.get("/{course_id}/gradebook", response_model=GradebookRead)
async def get_gradebook(
    course_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> GradebookRead:
    course = await _get_owned_course(course_id, user, db)
    return await gradebook_service.get_gradebook(course_id, course.title, db)


@router.patch(
    "/{course_id}/progress/{progress_id}",
    response_model=GradebookCellRead,
)
async def patch_progress(
    course_id: UUID,
    progress_id: UUID,
    data: ProgressUpdate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> GradebookCellRead:
    await _get_owned_course(course_id, user, db)
    updates = data.model_dump(exclude_unset=True)
    progress = await gradebook_service.patch_progress(course_id, progress_id, updates, db)
    lesson = await db.get(Lesson, progress.lesson_id)
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return GradebookCellRead(
        lesson_id=lesson.id,
        lesson_title=lesson.title,
        content_type=lesson.content_type.value,
        is_completed=progress.is_completed,
        quiz_score=progress.quiz_score,
        effective_score=gradebook_service.compute_effective_score(
            progress.quiz_score, progress.manual_score
        ),
        manual_score=progress.manual_score,
        teacher_comment=progress.teacher_comment,
        completed_at=progress.completed_at,
        progress_id=progress.id,
    )
