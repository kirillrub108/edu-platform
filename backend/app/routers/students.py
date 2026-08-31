import asyncio
from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sse_starlette.sse import EventSourceResponse

from app.constants import SSE_HEARTBEAT_SECONDS, SSE_RETRY_MS
from app.database import get_db
from app.dependencies import require_lesson_access, require_student
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
from app.redis_client import get_pubsub_redis
from app.routers.lessons import video_playback_url
from app.schemas.course import CoursePreview, StudentCourseOut
from app.schemas.gradebook import StudentCourseDetailRead, StudentLessonProgressRead
from app.schemas.lesson import LessonOut
from app.schemas.student import (
    NearestDeadlineRead,
    StudentAssignmentRead,
    StudentDashboardRead,
    StudentQuizRead,
    StudentResultRead,
)
from app.services import (
    course_access_service,
    course_stream,
    gradebook_service,
    visibility_service,
)
from app.services.progress_service import get_or_create_lesson_progress
from app.services.storage_service import storage_service

logger = structlog.get_logger()

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

    # Archive (`deleted_at`) and unpublish (`is_published`) are independent
    # levers and either one closes the course to NEW enrollments — a course can
    # be archived while still published, so both are checked. Both answer 404,
    # never 400/403, so the API doesn't reveal that an archived or draft course
    # exists. Neither affects a student who is ALREADY enrolled: see
    # services/visibility_service.py.
    if not course or course.deleted_at is not None or not course.is_published:
        raise HTTPException(status_code=404, detail="Course not available")

    # Restricted course: only students the owner listed may get on, and the
    # answer is the same 403 whether the access_code was right or wrong.
    if course_access_service.is_restricted(course) and not await course_access_service.has_grant(
        db, user.id, course.id
    ):
        raise HTTPException(status_code=403, detail="Course access is restricted")

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
        .where(
            Enrollment.student_id == user.id,
            course_access_service.access_clause(user.id),
        )
        .options(
            selectinload(Enrollment.course).selectinload(Course.owner),
            selectinload(Enrollment.course)
            .selectinload(Course.modules)
            .selectinload(Module.lessons),
            selectinload(Enrollment.progress),
        )
    )
    result = []
    for enrollment in enrollments.all():
        course = enrollment.course
        # Count only lessons the student can actually see (full publish chain,
        # plus the ones retained by their own progress).
        progressed = {p.lesson_id for p in enrollment.progress}
        course.lessons_count = sum(
            1
            for module in course.modules
            for lesson in module.lessons
            if visibility_service.lesson_visible_to_student(module, lesson, lesson.id in progressed)
        )
        out = StudentCourseOut.model_validate(course)
        out.completed_lessons = sum(1 for p in enrollment.progress if p.is_completed)
        if course.cover_image_path:
            out.cover_image_url = storage_service.get_url(course.cover_image_path, str(user.id))
        elif course.cover_url:
            out.cover_image_url = storage_service.resign_url(course.cover_url, str(user.id))
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


@router.get("/courses/stream")
async def courses_stream(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_pubsub_redis),
):
    """Pushes course-access changes to the student's cabinet so a course the
    teacher just granted (or revoked) appears without a reload.

    Registered ABOVE `/courses/{course_id}` on purpose — declared after it, the
    path parameter would swallow "stream" and answer 422.

    Unlike the lesson progress stream in routers/lessons.py, this does NOT open
    a Redis subscription per connection — `services/course_stream.py` keeps one
    pattern subscription per worker and hands out asyncio queues, so Redis
    connections stay O(workers) instead of O(open tabs) (DECISIONS §62). There
    is no snapshot to replay either: the client refetches its list on any
    message, and the cabinet also refetches on tab focus, so a dropped or
    unavailable stream degrades to that instead of going stale.
    """
    student_id = user.id

    # Authentication is done, so hand the pooled DB connection back BEFORE the
    # stream starts. FastAPI holds the request-scoped session until the response
    # completes, and an SSE response never completes — without this every open
    # tab pins a connection and the pool (5 + 10 overflow) runs dry at ~15
    # concurrent streams, which is a far lower ceiling than the Redis one this
    # endpoint was built to avoid. close() is idempotent; get_db closes again.
    await db.close()

    # Must fail before EventSourceResponse — once it is returned the headers are
    # sent and a 503 can no longer be raised.
    try:
        await redis.ping()
    except Exception:
        raise HTTPException(status_code=503, detail="Streaming unavailable")

    async def generator():
        # `retry` tells the browser how fast to come back; a blue-green switch
        # cuts open streams when the old slot drains.
        yield {"retry": SSE_RETRY_MS, "comment": "stream open"}

        try:
            async with course_stream.subscribe(redis, student_id) as queue:
                while True:
                    try:
                        data = await asyncio.wait_for(queue.get(), timeout=SSE_HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        # Idle long enough — keep the connection warm and let a
                        # dead client be noticed.
                        yield {"comment": "ping"}
                        continue
                    yield {"data": data}
        except Exception:
            # Headers are already sent so we cannot 503 — end the stream and let
            # the cabinet fall back to refetching when the tab regains focus.
            logger.warning("courses_stream_failed", student_id=str(student_id))
            return

    return EventSourceResponse(generator())


@router.get("/courses/{course_id}", response_model=StudentCourseDetailRead)
async def course_details(
    course_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> StudentCourseDetailRead:
    enrollment = await course_access_service.get_enrollment(db, user.id, course_id)
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

    progress_rows = (
        await db.scalars(
            select(LessonProgress).where(LessonProgress.enrollment_id == enrollment.id)
        )
    ).all()
    lesson_progress = {
        str(p.lesson_id): StudentLessonProgressRead(
            effective_score=gradebook_service.compute_effective_score(p.quiz_score, p.manual_score),
            teacher_comment=p.teacher_comment,
            is_completed=p.is_completed,
        )
        for p in progress_rows
    }

    resp = StudentCourseDetailRead.model_validate(course)
    # Students only see modules/lessons whose full publish chain is published —
    # plus the ones their own progress retains, already loaded just above.
    resp.modules = visibility_service.visible_module_tree(
        course, {p.lesson_id for p in progress_rows}
    )
    resp.lesson_progress = lesson_progress
    return resp


@router.get("/lessons/{lesson_id}", response_model=LessonOut)
async def get_lesson_for_student(
    access: tuple[User, Lesson, bool] = Depends(require_lesson_access),
):
    """`require_lesson_access` owns the whole gate (enrollment + the publish
    AND-rule with the retained-progress exception), so this route never
    re-derives it — visibility_service stays the single source of truth."""
    user, lesson, _is_owner = access

    out = LessonOut.model_validate(lesson)
    out.hidden_by_author = visibility_service.lesson_hidden_by_author(lesson.module, lesson)
    out.video_url = video_playback_url(lesson.id, None, lesson.video_url, str(user.id))
    return out


async def _get_progress(user: User, lesson: Lesson, db: AsyncSession) -> LessonProgress:
    """Access is already settled by `require_lesson_access`; what is left is the
    enrollment row the progress hangs off (owners have none → 403)."""
    enrollment = await course_access_service.get_enrollment(db, user.id, lesson.module.course_id)
    if not enrollment:
        raise HTTPException(status_code=403, detail="Not enrolled")

    return await get_or_create_lesson_progress(db, enrollment_id=enrollment.id, lesson_id=lesson.id)


@router.post("/lessons/{lesson_id}/complete")
async def complete_lesson(
    access: tuple[User, Lesson, bool] = Depends(require_lesson_access),
    db: AsyncSession = Depends(get_db),
):
    user, lesson, _is_owner = access
    if lesson.content_type == ContentType.quiz:
        raise HTTPException(
            status_code=400,
            detail="Quiz lessons are completed automatically upon passing the quiz",
        )
    progress = await _get_progress(user, lesson, db)
    progress.is_completed = True
    progress.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return {"lesson_id": str(lesson.id), "completed": True}


# ── Personal cabinet (dashboard + list pages) ───────────────────────────────
# Read-only aggregates/lists feeding the student cabinet. Scores are normalized
# 0..1 in the DB and exposed here as 0..100 percentages.


@router.get("/dashboard", response_model=StudentDashboardRead)
async def dashboard(
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> StudentDashboardRead:
    accessible = (
        select(Enrollment.id.label("enrollment_id"), Enrollment.course_id.label("course_id"))
        .join(Course, Enrollment.course_id == Course.id)
        .where(
            Enrollment.student_id == user.id,
            course_access_service.access_clause(user.id),
        )
        .subquery()
    )
    enrollment_ids = select(accessible.c.enrollment_id).scalar_subquery()
    course_ids = select(accessible.c.course_id).scalar_subquery()

    enrolled_courses = await db.scalar(select(func.count()).select_from(accessible))

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
            and_(
                Enrollment.course_id == Course.id,
                Enrollment.student_id == user.id,
                course_access_service.access_clause(user.id),
            ),
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
        .order_by(func.coalesce(QuizAttempt.submitted_at, QuizAttempt.started_at).desc())
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
            and_(
                Enrollment.course_id == Course.id,
                Enrollment.student_id == user.id,
                course_access_service.access_clause(user.id),
            ),
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
