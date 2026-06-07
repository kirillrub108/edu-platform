import asyncio
import json
from uuid import UUID

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.celery_app import celery_app
from app.database import get_db
from app.dependencies import (
    get_current_user,
    get_owned_lesson,
    require_teacher,
    require_verified_teacher,
)
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.lesson import CreationMode, Lesson, LessonStatus, Module
from app.models.lesson_video import LessonVideo
from app.models.quiz import AttemptStatus, Quiz, QuizAttempt, QuizQuestion
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.lesson import (
    LessonCreate,
    LessonOut,
    LessonUpdate,
    LessonVideoOut,
    ScriptUpdateRequest,
    TaskStatusResponse,
    VideoGenerateRequest,
)
from app.limiter import limiter
from app.schemas.quiz import QuizQuestionTeacherRead, QuizTeacherResultRow
from app.constants import CREDIT_WEIGHTS
from app.services import billing_service
from app.services.storage_service import storage_service
from app.tasks.video_pipeline import generate_video_lesson


def _lesson_out(
    lesson: Lesson, user_id: str, published_video: LessonVideoOut | None = None
) -> LessonOut:
    out = LessonOut.model_validate(lesson)
    out.video_url = storage_service.resign_url(out.video_url, user_id)
    out.published_video = published_video
    return out


def _video_out(video: LessonVideo, user_id: str) -> LessonVideoOut:
    out = LessonVideoOut.model_validate(video)
    out.video_url = storage_service.resign_url(out.video_url, user_id)
    return out


router = APIRouter(prefix="/api/v1/lessons", tags=["lessons"])


@router.post("/", response_model=LessonOut, status_code=status.HTTP_201_CREATED)
async def create_lesson(
    data: LessonCreate,
    user: User = Depends(require_verified_teacher),
    db: AsyncSession = Depends(get_db),
):
    module = await db.get(Module, data.module_id)
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    course = await db.get(Course, module.course_id)
    if course.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not your course")

    lesson = Lesson(
        title=data.title,
        module_id=data.module_id,
        content_type=data.content_type,
        order=data.order,
        creation_mode=data.creation_mode,
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return _lesson_out(lesson, str(user.id))


@router.get("/{lesson_id}", response_model=LessonOut)
async def get_lesson(
    lesson_id: UUID,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LessonVideo)
        .where(LessonVideo.lesson_id == lesson_id, LessonVideo.is_published.is_(True))
        .limit(1)
    )
    published = result.scalar_one_or_none()
    published_out = _video_out(published, str(user.id)) if published else None
    return _lesson_out(lesson, str(user.id), published_out)


@router.put("/{lesson_id}", response_model=LessonOut)
async def update_lesson(
    lesson_id: UUID,
    data: LessonUpdate,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(lesson, key, value)
    await db.commit()
    await db.refresh(lesson)
    return _lesson_out(lesson, str(user.id))


@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    await db.delete(lesson)
    await db.commit()


@router.put("/{lesson_id}/script", response_model=LessonOut)
async def update_script(
    lesson_id: UUID,
    data: ScriptUpdateRequest,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    lesson.script = data.script
    await db.commit()
    await db.refresh(lesson)
    return _lesson_out(lesson, str(user.id))


# TODO: в тестах сбрасывать лимитер через limiter.reset() или MemoryStorage в фикстуре
@router.post("/{lesson_id}/generate-video")
@limiter.limit("3/minute")
async def generate_video(
    request: Request,
    lesson_id: UUID,
    data: VideoGenerateRequest,
    user: User = Depends(require_verified_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    pptx_path = data.pptx_path or lesson.pptx_path
    if not pptx_path:
        raise HTTPException(
            status_code=400,
            detail="pptx_path is required (pass it in the body or upload a PPTX to the lesson first)",  # noqa: E501
        )

    # Persist pptx_path on the lesson so it can be reused on retries
    if data.pptx_path and data.pptx_path != lesson.pptx_path:
        lesson.pptx_path = data.pptx_path
        await db.commit()

    is_regen = lesson.status == LessonStatus.published
    cost_key = "lesson_regen" if is_regen else "lesson_generate"
    balance = await billing_service.get_balance(db, user.id)
    if balance["available"] < CREDIT_WEIGHTS[cost_key]:
        raise HTTPException(status_code=402, detail="Недостаточно кредитов для генерации видео")

    task = generate_video_lesson.apply_async(
        args=[str(lesson.id), pptx_path, data.voice], queue="video"
    )
    lesson.video_task_id = task.id
    await db.commit()
    return {"task_id": task.id, "lesson_id": str(lesson.id)}


@router.post("/{lesson_id}/cancel-video")
async def cancel_video(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    task_id = lesson.video_task_id
    if task_id:
        result = AsyncResult(task_id, app=celery_app)
        result.revoke(terminate=True, signal="SIGKILL")
        lesson.video_task_id = None

    if lesson.creation_mode == CreationMode.presentation_auto:
        lesson.status = LessonStatus.ready_for_edit
    else:
        lesson.status = LessonStatus.draft
    await db.commit()

    # A terminated task's `finally` block may not run, so its reserved credit
    # hold would leak. Release it idempotently (no-op if the task already
    # finalized before the revoke landed).
    owner_id = lesson.module.course.owner_id
    await billing_service.release_reservation_if_held(db, owner_id, str(lesson_id))
    return {"cancelled": True, "lesson_id": str(lesson_id)}


_LESSON_STATUS_TO_CELERY: dict[LessonStatus, str] = {
    LessonStatus.draft: "PENDING",
    LessonStatus.analyzing: "PROGRESS",
    LessonStatus.ready_for_edit: "PENDING",
    LessonStatus.processing: "PROGRESS",
    LessonStatus.published: "SUCCESS",
    LessonStatus.error: "FAILURE",
}


@router.get("/{lesson_id}/task-status/{task_id}", response_model=TaskStatusResponse)
async def task_status(
    lesson_id: UUID,
    task_id: str,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    celery_status = _LESSON_STATUS_TO_CELERY.get(lesson.status, "PENDING")

    payload: dict = {
        "task_id": task_id,
        "status": celery_status,
        "result": None,
        "meta": None,
        "progress_pct": None,
        "error": None,
    }

    if lesson.status == LessonStatus.published:
        latest_result = await db.execute(
            select(LessonVideo)
            .where(LessonVideo.lesson_id == lesson_id)
            .order_by(LessonVideo.created_at.desc())
            .limit(1)
        )
        lv = latest_result.scalar_one_or_none()
        payload["result"] = {
            "video_url": lv.video_url if lv else lesson.video_url,
            "video_id": str(lv.id) if lv else None,
        }
        return payload

    # Try Redis for live progress details; fails gracefully if Redis is down.
    try:
        ar = AsyncResult(task_id, app=celery_app)
        if lesson.status == LessonStatus.error:
            payload["error"] = (
                str(ar.result) if ar.result is not None else "Video generation failed"
            )  # noqa: E501
            payload["traceback"] = ar.traceback
            return payload
        if ar.state == "PROGRESS" and isinstance(ar.info, dict):
            payload["meta"] = ar.info
            done = ar.info.get("done", 0)
            total = ar.info.get("total", 1) or 1
            payload["progress_pct"] = round(done / total * 100)
    except Exception:
        pass

    return payload


_SSE_TERMINAL = {"published", "ready_for_edit", "error"}


@router.get("/{lesson_id}/progress-stream")
async def progress_stream(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    redis: Redis = Depends(get_redis),
):
    """SSE stream of Celery task progress for a lesson.

    Publishes `{step, done, total}` events while a task runs and a terminal
    `{status}` event when the task finishes. Uses Redis pub/sub on the
    `lesson:{lesson_id}` channel populated by the Celery workers.

    Auth via the `access_token` httpOnly cookie (same as all other endpoints).
    EventSource sends cookies when `withCredentials: true` is set.
    """
    # Capture terminal state before the generator starts (DB session is still alive here).
    terminal_payload: dict | None = None
    if lesson.status == LessonStatus.published:
        terminal_payload = {"status": "published", "video_url": lesson.video_url}
    elif lesson.status == LessonStatus.error:
        terminal_payload = {"status": "error"}
    elif lesson.status == LessonStatus.ready_for_edit:
        terminal_payload = {"status": "ready_for_edit"}

    # Probe Redis before committing to streaming (only needed for live path).
    # Must happen here — once EventSourceResponse is returned, HTTP headers are
    # already sent and a 503 can no longer be raised.
    if terminal_payload is None:
        try:
            await redis.ping()
        except Exception:
            raise HTTPException(status_code=503, detail="Streaming unavailable")

    channel = f"lesson:{lesson_id}"

    async def generator():
        # If the lesson is already in a terminal state, emit once and close.
        if terminal_payload is not None:
            yield {"data": json.dumps(terminal_payload)}
            return

        pubsub = redis.pubsub()
        try:
            await pubsub.subscribe(channel)

            # Emit a snapshot of the last known Celery progress so the UI
            # doesn't start blank after a page reload. Subscribe first so we
            # don't miss any message published between the snapshot read and
            # the subscribe call. Mirrors the /task-status endpoint pattern.
            task_id = lesson.video_task_id or lesson.analyze_task_id
            if task_id:
                try:
                    ar = AsyncResult(str(task_id), app=celery_app)
                    if ar.state == "PROGRESS" and isinstance(ar.info, dict):
                        yield {"data": json.dumps(ar.info)}
                except Exception:
                    pass

            last_heartbeat = asyncio.get_running_loop().time()
            while True:
                # get_message with timeout=1.0 waits up to 1 s for a message,
                # returning None on timeout — keeps the generator responsive to
                # client disconnects and heartbeat intervals without busy-looping.
                msg = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if msg and msg["type"] == "message":
                    yield {"data": msg["data"]}
                    try:
                        data = json.loads(msg["data"])
                        if data.get("status") in _SSE_TERMINAL:
                            return
                    except json.JSONDecodeError:
                        pass

                now = asyncio.get_running_loop().time()
                if now - last_heartbeat >= 15.0:
                    yield {"comment": "ping"}
                    last_heartbeat = now
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.aclose()

    return EventSourceResponse(generator())


@router.get("/{lesson_id}/quiz/questions", response_model=list[QuizQuestionTeacherRead])
async def get_quiz_questions(
    lesson_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    lesson = await db.scalar(select(Lesson).where(Lesson.id == lesson_id))
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    quiz = await db.scalar(select(Quiz).where(Quiz.lesson_id == lesson_id))
    if quiz is None:
        return []
    result = await db.execute(
        select(QuizQuestion)
        .where(QuizQuestion.quiz_id == quiz.id, QuizQuestion.superseded_at.is_(None))
        .order_by(QuizQuestion.order)
    )
    return result.scalars().all()


@router.get("/{lesson_id}/quiz-results", response_model=list[QuizTeacherResultRow])
async def quiz_results(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    """Best-attempt aggregation per enrolled student. A student with no
    attempts shows up with `attempts_count=0` so the teacher sees who hasn't
    tried the test yet.
    """
    course_id = lesson.module.course_id
    quiz = await db.scalar(select(Quiz).where(Quiz.lesson_id == lesson_id))
    quiz_id = quiz.id if quiz is not None else None
    pass_threshold = quiz.pass_threshold if quiz is not None else None

    students = (
        await db.execute(
            select(User)
            .join(Enrollment, Enrollment.student_id == User.id)
            .where(Enrollment.course_id == course_id)
            .order_by(User.full_name)
        )
    ).scalars().all()

    out: list[QuizTeacherResultRow] = []
    for student in students:
        if quiz_id is None:
            out.append(QuizTeacherResultRow(
                student_id=student.id,
                full_name=student.full_name,
                email=student.email,
                best_score=None,
                attempts_count=0,
                passed=False,
                last_submitted_at=None,
            ))
            continue
        # Only count graded attempts toward best_score; submitted-but-pending
        # attempts shouldn't influence a published number.
        attempts = (
            await db.execute(
                select(QuizAttempt)
                .where(
                    QuizAttempt.quiz_id == quiz_id,
                    QuizAttempt.student_id == student.id,
                )
                .order_by(desc(QuizAttempt.submitted_at))
            )
        ).scalars().all()
        graded = [a for a in attempts if a.status == AttemptStatus.graded and a.score is not None]
        best = max(graded, key=lambda a: a.score) if graded else None
        last_subm = next((a.submitted_at for a in attempts if a.submitted_at), None)
        passed = bool(best and pass_threshold is not None and best.score >= pass_threshold)
        out.append(QuizTeacherResultRow(
            student_id=student.id,
            full_name=student.full_name,
            email=student.email,
            best_score=best.score if best else None,
            attempts_count=len(attempts),
            passed=passed,
            last_submitted_at=last_subm,
        ))
    return out


@router.get("/{lesson_id}/videos", response_model=list[LessonVideoOut])
async def list_videos(
    lesson_id: UUID,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LessonVideo)
        .where(LessonVideo.lesson_id == lesson_id)
        .order_by(LessonVideo.created_at.desc())
    )
    return [_video_out(v, str(user.id)) for v in result.scalars().all()]


@router.post("/{lesson_id}/videos/{video_id}/publish", response_model=LessonVideoOut)
async def publish_video(
    lesson_id: UUID,
    video_id: UUID,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LessonVideo).where(
            LessonVideo.id == video_id,
            LessonVideo.lesson_id == lesson_id,
        )
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Idempotent: already published — return as-is.
    if video.is_published:
        return _video_out(video, str(user.id))

    # Unpublish all other videos for this lesson.
    await db.execute(
        update(LessonVideo)
        .where(LessonVideo.lesson_id == lesson_id, LessonVideo.is_published.is_(True))
        .values(is_published=False)
    )

    video.is_published = True
    # Keep lesson.video_url in sync so the student player keeps working.
    lesson.video_url = video.video_url
    await db.commit()
    await db.refresh(video)

    return _video_out(video, str(user.id))
