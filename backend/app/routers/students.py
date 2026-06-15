from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import require_student
from app.limiter import limiter
from app.models.assignment import (
    Assignment,
    AssignmentStatus,
    AssignmentSubmission,
    SubmissionStatus,
)
from app.models.course import Course
from app.models.enrollment import Enrollment, LessonProgress
from app.models.lesson import ContentType, Lesson, Module
from app.models.quiz import AttemptStatus, Quiz, QuizAttempt, QuizStatus
from app.models.user import User
from app.schemas.course import CourseOut, CoursePreview, StudentCourseOut
from app.schemas.gradebook import StudentCourseDetailRead, StudentLessonProgressRead
from app.schemas.lesson import LessonOut
from app.schemas.student import (
    NearestDeadlineRead,
    StudentAssignmentRead,
    StudentDashboardRead,
    StudentQuizRead,
    StudentResultRead,
)
from app.services import gradebook_service, visibility_service
from app.services.progress_service import get_or_create_lesson_progress
from app.constants import SIGNED_URL_TTL_VIDEO
from app.services.storage_service import storage_service

router = APIRouter(prefix="/api/v1/students", tags=["students"])


class EnrollRequest(BaseModel):
    course_id: UUID | None = None
    access_code: str | None = None


@router.post("/enroll")
@limiter.limit("10/minute")
async def enroll(
    request: Request,
    data: EnrollRequest,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    course: Course | None = None
    if data.course_id:
        course = await db.scalar(select(Course).where(Course.id == data.course_id))
    elif data.access_code:
        course = await db.scalar(select(Course).where(Course.access_code == data.access_code))

    if not course:
        raise HTTPException(status_code=404, detail="Course not available")
    if course.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Course is not available")
    if not course.is_published:
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


@router.get("/my-courses", response_model=list[StudentCourseOut])
async def my_courses(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    enrollments = await db.scalars(
        select(Enrollment)
        .join(Course, Enrollment.course_id == Course.id)
        .where(Enrollment.student_id == user.id)
        .options(
            selectinload(Enrollment.course).selectinload(Course.owner),
            selectinload(Enrollment.course).selectinload(Course.modules).selectinload(Module.lessons),
            selectinload(Enrollment.progress),
        )
    )
    result = []
    for enrollment in enrollments.all():
        course = enrollment.course
        # Count only lessons the student can actually see (full publish chain).
        course.lessons_count = sum(
            1
            for module in course.modules
            for lesson in module.lessons
            if visibility_service.lesson_visible_to_student(course, module, lesson)
        )
        out = StudentCourseOut.model_validate(course)
        out.completed_lessons = sum(1 for p in enrollment.progress if p.is_completed)
        result.append(out)
    return result


@router.get("/courses/preview", response_model=CoursePreview)
async def preview_course(
    code: str | None = None,
    course_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    course: Course | None = None
    if code:
        course = await db.scalar(
            select(Course).where(Course.access_code == code, Course.deleted_at.is_(None))
        )
    elif course_id:
        course = await db.scalar(
            select(Course).where(Course.id == course_id, Course.deleted_at.is_(None))
        )

    if not course or not course.is_published:
        raise HTTPException(status_code=404, detail="Course not found")

    return course


@router.get("/courses/{course_id}", response_model=StudentCourseDetailRead)
async def course_details(
    course_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> StudentCourseDetailRead:
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

    progress_rows = await db.scalars(
        select(LessonProgress).where(LessonProgress.enrollment_id == enrollment.id)
    )
    lesson_progress = {
        str(p.lesson_id): StudentLessonProgressRead(
            effective_score=gradebook_service.compute_effective_score(
                p.quiz_score, p.manual_score
            ),
            teacher_comment=p.teacher_comment,
            is_completed=p.is_completed,
        )
        for p in progress_rows.all()
    }

    resp = StudentCourseDetailRead.model_validate(course)
    # Students only see modules/lessons whose full publish chain is published.
    resp.modules = visibility_service.visible_module_tree(course)
    resp.lesson_progress = lesson_progress
    return resp


@router.get("/lessons/{lesson_id}", response_model=LessonOut)
async def get_lesson_for_student(
    lesson_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    lesson = await db.scalar(select(Lesson).where(Lesson.id == lesson_id))
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

    # A draft anywhere in the chain hides the lesson — 404, never leak a draft.
    course = await db.get(Course, module.course_id)
    if not visibility_service.lesson_visible_to_student(course, module, lesson):
        raise HTTPException(status_code=404, detail="Lesson not found")

    out = LessonOut.model_validate(lesson)
    if out.video_url is not None:
        out.video_url = storage_service.resign_url(out.video_url, str(user.id), expires_in=SIGNED_URL_TTL_VIDEO)
    return out


async def _get_progress(user: User, lesson_id: UUID, db: AsyncSession) -> LessonProgress:
    lesson = await db.scalar(select(Lesson).where(Lesson.id == lesson_id))
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

    return await get_or_create_lesson_progress(
        db, enrollment_id=enrollment.id, lesson_id=lesson_id
    )


@router.post("/lessons/{lesson_id}/complete")
async def complete_lesson(
    lesson_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
):
    lesson = await db.scalar(select(Lesson).where(Lesson.id == lesson_id))
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    if lesson.content_type == ContentType.quiz:
        raise HTTPException(
            status_code=400,
            detail="Quiz lessons are completed automatically upon passing the quiz",
        )
    progress = await _get_progress(user, lesson_id, db)
    progress.is_completed = True
    progress.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"lesson_id": str(lesson_id), "completed": True}


# ── Personal cabinet (dashboard + list pages) ───────────────────────────────
# Read-only aggregates/lists feeding the student cabinet. Scores are normalized
# 0..1 in the DB and exposed here as 0..100 percentages.


@router.get("/dashboard", response_model=StudentDashboardRead)
async def dashboard(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> StudentDashboardRead:
    enrollment_ids = (
        select(Enrollment.id).where(Enrollment.student_id == user.id).scalar_subquery()
    )
    course_ids = (
        select(Enrollment.course_id)
        .where(Enrollment.student_id == user.id)
        .scalar_subquery()
    )

    enrolled_courses = await db.scalar(
        select(func.count())
        .select_from(Enrollment)
        .where(Enrollment.student_id == user.id)
    )

    # "Выполнено заданий" — assignments handed in (anything past the draft stage).
    completed_assignments = await db.scalar(
        select(func.count())
        .select_from(AssignmentSubmission)
        .where(
            AssignmentSubmission.enrollment_id.in_(enrollment_ids),
            AssignmentSubmission.status != SubmissionStatus.draft,
        )
    )

    # "Средний балл" — mean of submitted/graded quiz attempts.
    avg_score = await db.scalar(
        select(func.avg(QuizAttempt.score)).where(
            QuizAttempt.student_id == user.id,
            QuizAttempt.status.in_([AttemptStatus.submitted, AttemptStatus.graded]),
            QuizAttempt.score.isnot(None),
        )
    )

    # "Ближайший дедлайн" — next upcoming published assignment in an enrolled course.
    now = datetime.now(timezone.utc)
    deadline_row = (
        await db.execute(
            select(Assignment, Course.title)
            .join(Lesson, Assignment.lesson_id == Lesson.id)
            .join(Module, Lesson.module_id == Module.id)
            .join(Course, Module.course_id == Course.id)
            .where(
                Module.course_id.in_(course_ids),
                Assignment.status == AssignmentStatus.published,
                Assignment.due_at.isnot(None),
                Assignment.due_at > now,
            )
            .order_by(Assignment.due_at.asc())
            .limit(1)
        )
    ).first()

    nearest_deadline = None
    if deadline_row is not None:
        assignment, course_title = deadline_row
        nearest_deadline = NearestDeadlineRead(
            assignment_id=assignment.id,
            title=assignment.title,
            course_title=course_title,
            due_at=assignment.due_at,
        )

    return StudentDashboardRead(
        enrolled_courses=enrolled_courses or 0,
        completed_assignments=completed_assignments or 0,
        average_score=round(float(avg_score) * 100, 1) if avg_score is not None else None,
        nearest_deadline=nearest_deadline,
    )


@router.get("/quizzes", response_model=list[StudentQuizRead])
async def my_quizzes(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> list[StudentQuizRead]:
    rows = await db.execute(
        select(
            Lesson.id.label("lesson_id"),
            Lesson.title.label("title"),
            Course.id.label("course_id"),
            Course.title.label("course_title"),
            Quiz.attempts_allowed.label("attempts_allowed"),
            LessonProgress.quiz_score.label("quiz_score"),
            LessonProgress.is_completed.label("is_completed"),
        )
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .join(
            Enrollment,
            and_(Enrollment.course_id == Course.id, Enrollment.student_id == user.id),
        )
        .join(
            Quiz,
            and_(Quiz.lesson_id == Lesson.id, Quiz.status == QuizStatus.published),
        )
        .outerjoin(
            LessonProgress,
            and_(
                LessonProgress.lesson_id == Lesson.id,
                LessonProgress.enrollment_id == Enrollment.id,
            ),
        )
        .where(Lesson.content_type == ContentType.quiz)
        .order_by(Course.title, Lesson.order)
    )

    return [
        StudentQuizRead(
            lesson_id=r.lesson_id,
            course_id=r.course_id,
            title=r.title,
            course_title=r.course_title,
            best_score=round(r.quiz_score * 100, 1) if r.quiz_score is not None else None,
            is_passed=bool(r.is_completed),
            attempts_allowed=r.attempts_allowed,
        )
        for r in rows.all()
    ]


@router.get("/results", response_model=list[StudentResultRead])
async def my_results(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> list[StudentResultRead]:
    rows = await db.execute(
        select(
            QuizAttempt.id.label("attempt_id"),
            QuizAttempt.score.label("score"),
            QuizAttempt.passed.label("passed"),
            QuizAttempt.status.label("status"),
            QuizAttempt.submitted_at.label("submitted_at"),
            QuizAttempt.started_at.label("started_at"),
            Lesson.id.label("lesson_id"),
            Lesson.title.label("title"),
            Course.id.label("course_id"),
            Course.title.label("course_title"),
        )
        .join(Quiz, QuizAttempt.quiz_id == Quiz.id)
        .join(Lesson, Quiz.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .where(
            QuizAttempt.student_id == user.id,
            QuizAttempt.status.in_([AttemptStatus.submitted, AttemptStatus.graded]),
        )
        .order_by(
            func.coalesce(QuizAttempt.submitted_at, QuizAttempt.started_at).desc()
        )
    )

    return [
        StudentResultRead(
            attempt_id=r.attempt_id,
            lesson_id=r.lesson_id,
            course_id=r.course_id,
            title=r.title,
            course_title=r.course_title,
            date=r.submitted_at or r.started_at,
            score=round(float(r.score) * 100, 1) if r.score is not None else None,
            passed=r.passed,
            status=r.status.value,
        )
        for r in rows.all()
    ]


@router.get("/assignments", response_model=list[StudentAssignmentRead])
async def my_assignments(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> list[StudentAssignmentRead]:
    rows = await db.execute(
        select(
            Assignment.id.label("assignment_id"),
            Assignment.title.label("title"),
            Assignment.due_at.label("due_at"),
            Assignment.max_points.label("max_points"),
            Lesson.id.label("lesson_id"),
            Course.id.label("course_id"),
            Course.title.label("course_title"),
            AssignmentSubmission.status.label("submission_status"),
            AssignmentSubmission.score.label("submission_score"),
        )
        .join(Lesson, Assignment.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .join(
            Enrollment,
            and_(Enrollment.course_id == Course.id, Enrollment.student_id == user.id),
        )
        .outerjoin(
            AssignmentSubmission,
            and_(
                AssignmentSubmission.assignment_id == Assignment.id,
                AssignmentSubmission.enrollment_id == Enrollment.id,
            ),
        )
        .where(Assignment.status == AssignmentStatus.published)
        .order_by(Assignment.due_at.asc(), Course.title)
    )

    result: list[StudentAssignmentRead] = []
    for r in rows.all():
        status = r.submission_status
        # A score is only visible to the student once the teacher releases it.
        score = (
            round(float(r.submission_score) * 100, 1)
            if status == SubmissionStatus.returned and r.submission_score is not None
            else None
        )
        result.append(
            StudentAssignmentRead(
                assignment_id=r.assignment_id,
                lesson_id=r.lesson_id,
                course_id=r.course_id,
                title=r.title,
                course_title=r.course_title,
                due_at=r.due_at,
                max_points=float(r.max_points),
                submission_status=status.value if status is not None else None,
                score=score,
            )
        )
    return result


