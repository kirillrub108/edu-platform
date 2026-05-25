from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import require_student
from app.models.course import Course
from app.models.enrollment import Enrollment, LessonProgress
from app.models.lesson import Lesson, Module
from app.models.user import User
from app.schemas.course import CourseDetail, CourseOut
from app.schemas.lesson import LessonOut
from app.services.storage_service import storage_service

router = APIRouter(prefix="/api/v1/students", tags=["students"])


class EnrollRequest(BaseModel):
    course_id: UUID | None = None
    access_code: str | None = None


@router.post("/enroll")
async def enroll(
    data: EnrollRequest,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    course: Course | None = None
    if data.course_id:
        course = await db.get(Course, data.course_id)
    elif data.access_code:
        course = await db.scalar(select(Course).where(Course.access_code == data.access_code))

    if not course or not course.is_published:
        raise HTTPException(status_code=404, detail="Course not available")

    existing = await db.scalar(
        select(Enrollment).where(
            Enrollment.student_id == user.id, Enrollment.course_id == course.id
        )
    )
    if existing:
        return {"enrollment_id": str(existing.id), "course_id": str(course.id)}

    enrollment = Enrollment(student_id=user.id, course_id=course.id)
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    return {"enrollment_id": str(enrollment.id), "course_id": str(course.id)}


@router.get("/my-courses", response_model=list[CourseOut])
async def my_courses(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    result = await db.scalars(
        select(Course)
        .join(Enrollment, Enrollment.course_id == Course.id)
        .where(Enrollment.student_id == user.id)
        .options(selectinload(Course.owner))
    )
    return list(result.all())


@router.get("/courses/{course_id}", response_model=CourseDetail)
async def course_details(
    course_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.student_id == user.id, Enrollment.course_id == course_id
        )
    )
    if not enrollment:
        raise HTTPException(status_code=403, detail="Not enrolled")

    course = await db.scalar(
        select(Course)
        .where(Course.id == course_id)
        .options(
            selectinload(Course.owner),
            selectinload(Course.modules).selectinload(Module.lessons),
        )
    )
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


@router.get("/lessons/{lesson_id}", response_model=LessonOut)
async def get_lesson_for_student(
    lesson_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    lesson = await db.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    module = await db.get(Module, lesson.module_id)
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.student_id == user.id, Enrollment.course_id == module.course_id
        )
    )
    if not enrollment:
        raise HTTPException(status_code=403, detail="Not enrolled")

    out = LessonOut.model_validate(lesson)
    if out.video_url is not None:
        out.video_url = storage_service.resign_url(out.video_url, str(user.id))
    return out


async def _get_progress(user: User, lesson_id: UUID, db: AsyncSession) -> LessonProgress:
    lesson = await db.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    module = await db.get(Module, lesson.module_id)
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.student_id == user.id, Enrollment.course_id == module.course_id
        )
    )
    if not enrollment:
        raise HTTPException(status_code=403, detail="Not enrolled")

    progress = await db.scalar(
        select(LessonProgress).where(
            LessonProgress.enrollment_id == enrollment.id,
            LessonProgress.lesson_id == lesson_id,
        )
    )
    if not progress:
        progress = LessonProgress(enrollment_id=enrollment.id, lesson_id=lesson_id)
        db.add(progress)
        await db.flush()
    return progress


@router.post("/lessons/{lesson_id}/complete")
async def complete_lesson(
    lesson_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    progress = await _get_progress(user, lesson_id, db)
    progress.is_completed = True
    progress.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"lesson_id": str(lesson_id), "completed": True}


