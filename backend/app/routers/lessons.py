import asyncio
import json
import mimetypes
import os
from urllib.parse import quote
from uuid import UUID, uuid4

import structlog
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import RedirectResponse, Response
from redis.asyncio import Redis
from sqlalchemy import desc, func, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.celery_app import celery_app
from app.config import settings
from app.constants import (
    CREDIT_WEIGHTS,
    MAX_VIDEO_UPLOAD_BYTES,
    S3_PRESIGN_TTL_SECONDS,
    SIGNED_URL_TTL_VIDEO,
    TRIAL_MAX_SCRIPT_CHARS,
    TRIAL_MAX_SLIDES,
    VIDEO_XACCEL_ENABLED,
    VIDEO_XACCEL_INTERNAL_PREFIX,
)
from app.database import get_db
from app.dependencies import (
    get_current_user,
    get_owned_lesson,
    require_lesson_access,
    require_teacher,
    require_verified_teacher,
)
from app.limiter import limiter
from app.models.course import Course
from app.models.credit import CreditOperation
from app.models.enrollment import Enrollment
from app.models.lesson import CreationMode, Lesson, LessonStatus, Module
from app.models.lesson_video import LessonVideo
from app.models.quiz import AttemptStatus, Quiz, QuizAttempt, QuizQuestion
from app.models.slide_text import SlideText
from app.models.user import User
from app.redis_client import get_redis
from app.schemas.billing import (
    EstimateTrialOut,
    EstimateVideoOut,
    GenerationEstimateOut,
)
from app.schemas.lesson import (
    LessonCreate,
    LessonOut,
    LessonPartialUpdate,
    LessonUpdate,
    LessonVideoOut,
    ScriptUpdateRequest,
    TaskStatusResponse,
    VideoGenerateRequest,
)
from app.schemas.quiz import QuizQuestionTeacherRead, QuizTeacherResultRow
from app.services import billing_service, quota_service, tier_service
from app.services.storage_service import storage_service
from app.services.video_service import count_source_slides
from app.tasks.video_pipeline import generate_video_lesson

logger = structlog.get_logger()

_LESSON_ROUTE_PREFIX = "/api/v1/lessons"


def lesson_video_stream_path(lesson_id: UUID) -> str:
    """Relative URL of the authorised player-stream endpoint for a lesson's
    current video. Same-origin (Nuxt devProxy in dev, nginx `/api/` in prod), so
    the httpOnly session cookie rides along with the browser's <video> request."""
    return f"{_LESSON_ROUTE_PREFIX}/{lesson_id}/video/stream"


def lesson_video_render_stream_path(lesson_id: UUID, video_id: UUID) -> str:
    """Relative URL of the authorised stream endpoint for one specific render."""
    return f"{_LESSON_ROUTE_PREFIX}/{lesson_id}/videos/{video_id}/stream"


# Dev (local storage, no nginx) has the frontend talking to the backend
# cross-origin (absolute NUXT_PUBLIC_API_BASE) with no reverse proxy, so a
# <video> can't ride the SameSite session cookie to the same-origin /stream
# endpoint. There it loads a bearer-signed absolute /files URL directly instead —
# the same model covers use. Prod (nginx or S3) is same-origin and serves the
# player through /stream (X-Accel / presigned 302).
_VIDEO_DIRECT_SIGNED: bool = (
    settings.STORAGE_BACKEND == "local" and not VIDEO_XACCEL_ENABLED
)


def video_playback_url(
    lesson_id: UUID, video_id: UUID | None, stored_url: str | None, user_id: str
) -> str | None:
    """Player src for a lesson video: a bearer-signed absolute /files URL in dev
    (loaded cross-origin directly by <video>), else the same-origin /stream
    endpoint (enrollment + visibility re-checked per request)."""
    if not stored_url:
        return None
    if _VIDEO_DIRECT_SIGNED:
        return storage_service.resign_url(stored_url, user_id, expires_in=SIGNED_URL_TTL_VIDEO)
    if video_id is not None:
        return lesson_video_render_stream_path(lesson_id, video_id)
    return lesson_video_stream_path(lesson_id)


def _lesson_out(
    lesson: Lesson, user_id: str, published_video: LessonVideoOut | None = None
) -> LessonOut:
    out = LessonOut.model_validate(lesson)
    out.video_url = video_playback_url(lesson.id, None, lesson.video_url, user_id)
    out.published_video = published_video
    # Only when the module relationship is already loaded (get_owned_lesson
    # joinedloads it) — touching an unloaded relationship on AsyncSession
    # would raise MissingGreenlet.
    if "module" not in sa_inspect(lesson).unloaded:
        out.course_id = lesson.module.course_id
    return out


def _video_out(video: LessonVideo, user_id: str) -> LessonVideoOut:
    out = LessonVideoOut.model_validate(video)
    out.video_url = video_playback_url(video.lesson_id, video.id, video.video_url, user_id)
    return out


router = APIRouter(prefix=_LESSON_ROUTE_PREFIX, tags=["lessons"])


@router.post("/", response_model=LessonOut, status_code=status.HTTP_201_CREATED)
async def create_lesson(
    data: LessonCreate,
    user: User = Depends(require_teacher),
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


@router.patch("/{lesson_id}", response_model=LessonOut)
async def patch_lesson(
    lesson_id: UUID,
    data: LessonPartialUpdate,
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


_VIDEO_EXTS = {".mp4", ".webm", ".mov", ".mkv"}
_VIDEO_CONTENT_TYPES = {"video/mp4", "video/webm", "video/quicktime", "video/x-matroska"}


def _looks_like_video(head: bytes, ext: str) -> bool:
    """Cheap magic-byte sniff on the first 16 bytes to reject empty/corrupt files."""
    if ext in (".mp4", ".mov"):
        # ISO Base Media File Format: a top-level box type at offset 4.
        return head[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide")
    if ext in (".webm", ".mkv"):
        return head[:4] == b"\x1a\x45\xdf\xa3"  # EBML / Matroska header
    return False


@router.post("/{lesson_id}/upload-video", response_model=LessonOut)
async def upload_lesson_video(
    file: UploadFile,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    """Attach a ready-made video file to a lesson — no generation pipeline, no AI.

    Replaces any existing video and publishes the lesson. Validates format by both
    extension and content-type, sniffs magic bytes, and caps size at
    MAX_VIDEO_UPLOAD_BYTES.
    """
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _VIDEO_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"Допустимые форматы: {', '.join(sorted(_VIDEO_EXTS))}",
        )
    if file.content_type not in _VIDEO_CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="Неверный тип содержимого видео")

    if file.size is not None:
        if file.size == 0:
            raise HTTPException(status_code=400, detail="Пустой файл")
        if file.size > MAX_VIDEO_UPLOAD_BYTES:
            gb = MAX_VIDEO_UPLOAD_BYTES // (1024 * 1024 * 1024)
            raise HTTPException(
                status_code=413, detail=f"Файл слишком большой (максимум {gb} ГБ)"
            )

    head = await file.read(16)
    await file.seek(0)
    if not _looks_like_video(head, ext):
        raise HTTPException(status_code=400, detail="Файл повреждён или не является видео")

    relative = await storage_service.save_upload(file, "videos")
    lesson.video_url = storage_service.get_url(relative, str(user.id))
    lesson.creation_mode = CreationMode.video_upload
    lesson.status = LessonStatus.published
    # Direct upload "publishes immediately" (see the UI copy) — make the lesson
    # student-visible right away so the new is_published gate doesn't silently
    # hide it. The teacher can still unpublish from the lesson header.
    lesson.is_published = True
    await db.commit()
    await db.refresh(lesson)
    return _lesson_out(lesson, str(user.id))


async def _video_estimate(
    db: AsyncSession, lesson: Lesson, pptx_path: str | None
) -> tuple[str, int | None, int, int | None]:
    """(mode, slides, script_chars, credits) for a video-generation launch.

    Auto mode counts existing SlideText rows (exact); otherwise the slide
    count is read cheaply from the source PPTX/PDF without rendering. credits
    is None when the slide count cannot be determined.
    """
    is_auto = lesson.creation_mode == CreationMode.presentation_auto
    slides: int | None = None
    if is_auto:
        slides = (
            await db.scalar(
                select(func.count())
                .select_from(SlideText)
                .where(SlideText.lesson_id == lesson.id)
            )
            or None
        )
    if slides is None and pptx_path:
        try:
            slides = count_source_slides(storage_service.get_full_path(pptx_path))
        except Exception:
            slides = None
    script_chars = 0 if is_auto else len((lesson.script or lesson.text_content or "").strip())
    credits: int | None = None
    if slides:
        credits = (
            billing_service.estimate_video_auto(slides)
            if is_auto
            else billing_service.estimate_video_text(slides, script_chars)
        )
    return ("auto" if is_auto else "text"), slides, script_chars, credits


async def _trial_video_available(
    db: AsyncSession, user_id: UUID, plan: str, slides: int | None, script_chars: int
) -> tuple[dict, bool]:
    """(trial_state, video slot usable) — free plan, slots left, lecture fits caps."""
    trial = await quota_service.get_trial_state(db, user_id)
    fits = (
        slides is not None
        and slides <= TRIAL_MAX_SLIDES
        and script_chars <= TRIAL_MAX_SCRIPT_CHARS
    )
    return trial, plan == "free" and fits and trial["lectures_used"] < trial["lectures_limit"]


def _insufficient_credits_402(balance: dict, required: int, trial: dict) -> HTTPException:
    """402 payload: trial_exhausted for free accounts that burned their trial,
    insufficient_credits otherwise — both machine-readable for the frontend."""
    if balance["plan"] == "free" and trial["lectures_used"] >= trial["lectures_limit"]:
        return HTTPException(
            status_code=402,
            detail={
                "code": "trial_exhausted",
                "limit": trial["lectures_limit"],
                "used": trial["lectures_used"],
            },
        )
    return HTTPException(
        status_code=402,
        detail={
            "code": "insufficient_credits",
            "required": required,
            "available": balance["available"],
        },
    )


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

    # 1. Concurrency (read): one active generation per lesson.
    if lesson.status in (LessonStatus.processing, LessonStatus.analyzing):
        raise HTTPException(status_code=409, detail={"code": "generation_in_progress"})

    # Persist pptx_path on the lesson so it can be reused on retries
    if data.pptx_path and data.pptx_path != lesson.pptx_path:
        lesson.pptx_path = data.pptx_path
        await db.commit()

    # 2. Estimate (read).
    _mode, slides, script_chars, estimate = await _video_estimate(db, lesson, pptx_path)
    if estimate is None:
        raise HTTPException(
            status_code=422, detail="Не удалось определить число слайдов презентации"
        )

    is_regen = lesson.status == LessonStatus.published
    operation = CreditOperation.LESSON_REGEN if is_regen else CreditOperation.LESSON_GENERATE
    balance = await billing_service.get_balance(db, user.id)

    # 3. Trial slot or credit reservation (write, atomic).
    billing_ref = f"{lesson.id}:{uuid4().hex[:12]}"
    trial, trial_usable = await _trial_video_available(
        db, user.id, balance["plan"], slides, script_chars
    )
    billed_via = "credits"
    if trial_usable and await quota_service.try_consume_slot(
        db, user.id, quota_service.TRIAL_LECTURE, trial["lectures_limit"]
    ):
        billed_via = "trial"
    elif not await billing_service.reserve_credits(
        db, user.id, estimate, billing_ref, operation
    ):
        raise _insufficient_credits_402(balance, estimate, trial)

    # Billing state must be committed before apply_async — the worker reads it.
    lesson.credit_estimate = estimate if billed_via == "credits" else 0
    lesson.credits_spent = 0
    lesson.billing_ref = billing_ref if billed_via == "credits" else None
    lesson.billed_via = billed_via
    lesson.cancel_requested = False
    await db.commit()

    # Schedule paid tiers ahead of free ones (priority derived from the plan).
    priority = await tier_service.priority_for_user(db, user.id)
    try:
        task = generate_video_lesson.apply_async(
            args=[str(lesson.id), pptx_path, data.voice, is_regen],
            queue="video",
            priority=priority,
        )
    except Exception:
        # Broker down — compensate the reservation/slot taken above.
        claimed = await billing_service.claim_billing(db, lesson.id)
        if claimed == "credits":
            await billing_service.release_credits(db, user.id, estimate, billing_ref)
        elif claimed == "trial":
            await quota_service.release_slot(db, user.id, quota_service.TRIAL_LECTURE)
        raise HTTPException(status_code=503, detail="Не удалось поставить задачу в очередь")
    lesson.video_task_id = task.id
    await db.commit()
    return {
        "task_id": task.id,
        "lesson_id": str(lesson.id),
        "credit_estimate": estimate,
        "billed_via": billed_via,
    }


async def cancel_generation_impl(lesson: Lesson, db: AsyncSession, redis: Redis) -> dict:
    """Cancel the active video/vision generation of a lesson.

    Queued task (Celery state PENDING) → revoke + full refund + status rollback
    ('immediate'). Running task → cooperative: only the cancel_requested flag is
    set; the pipeline stops at its next per-slide checkpoint, charges for the
    processed slides and releases the rest ('cooperative'). The running task is
    never killed with terminate=True. Refunds are guarded by claim_billing, so
    a task that actually started despite a PENDING state (Redis restart) cannot
    be refunded twice.
    """
    if lesson.status == LessonStatus.processing:
        task_id, kind = lesson.video_task_id, "video"
    elif lesson.status == LessonStatus.analyzing:
        task_id, kind = lesson.analyze_task_id, "vision"
    else:
        return {"cancelled": False, "mode": "none", "status": lesson.status.value}

    lesson.cancel_requested = True
    await db.commit()

    state = "PENDING"
    if task_id:
        try:
            result = AsyncResult(task_id, app=celery_app)
            state = result.state
            if state == "PENDING":
                result.revoke()  # prevents a queued task from starting; no terminate
        except Exception:
            state = "STARTED"  # can't tell — let the cooperative path handle it

    if state != "PENDING":
        return {"cancelled": True, "mode": "cooperative", "status": lesson.status.value}

    # Snapshot scalars before claim_billing: its rollback path (already
    # settled) expires the instance, and a lazy re-load from the async
    # session would raise MissingGreenlet.
    owner_id = lesson.module.course.owner_id
    billing_ref = lesson.billing_ref
    creation_mode = lesson.creation_mode
    claimed = await billing_service.claim_billing(db, lesson.id)
    if claimed == "credits" and billing_ref:
        await billing_service.release_reservation_if_held(db, owner_id, billing_ref)
    elif claimed == "trial" and kind == "video":
        # Nothing was processed — the trial lecture slot goes back.
        await quota_service.release_slot(db, owner_id, quota_service.TRIAL_LECTURE)

    if kind == "video":
        lesson.video_task_id = None
        lesson.status = (
            LessonStatus.ready_for_edit
            if creation_mode == CreationMode.presentation_auto
            else LessonStatus.draft
        )
    else:
        lesson.analyze_task_id = None
        lesson.status = LessonStatus.draft
    lesson.cancel_requested = False
    await db.commit()

    try:
        await redis.publish(
            f"lesson:{lesson.id}", json.dumps({"status": "cancelled", "credits_spent": 0})
        )
    except Exception:
        pass
    return {
        "cancelled": True,
        "mode": "immediate",
        "status": lesson.status.value,
        "credits_spent": 0,
    }


@router.post("/{lesson_id}/cancel-generation")
async def cancel_generation(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    return await cancel_generation_impl(lesson, db, redis)


@router.post("/{lesson_id}/cancel-video")
async def cancel_video(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
):
    """Deprecated alias of cancel-generation kept for API compatibility."""
    result = await cancel_generation_impl(lesson, db, redis)
    return {"cancelled": result["cancelled"], "lesson_id": str(lesson_id), **result}


@router.get("/{lesson_id}/generation-estimate", response_model=GenerationEstimateOut)
async def generation_estimate(
    lesson_id: UUID,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    """Pre-launch cost estimate for the generation confirm dialog. Read-only —
    triggers no AI work, so it is deliberately not in AI_GATED_ENDPOINTS."""
    mode, slides, script_chars, credits = await _video_estimate(db, lesson, lesson.pptx_path)
    balance = await billing_service.get_balance(db, user.id)
    trial, video_trial = await _trial_video_available(
        db, user.id, balance["plan"], slides, script_chars
    )
    quiz_trial = (
        balance["plan"] == "free" and trial["quizzes_used"] < trial["quizzes_limit"]
    )
    return GenerationEstimateOut(
        video=EstimateVideoOut(
            mode=mode, slides=slides, script_chars=script_chars, credits=credits
        ),
        vision_credits=CREDIT_WEIGHTS["vision_analyze"],
        quiz_credits=CREDIT_WEIGHTS["quiz_generate"],
        ai_review_credits=CREDIT_WEIGHTS["ai_review"],
        available=balance["available"],
        plan=balance["plan"],
        trial=EstimateTrialOut(
            **trial, video_trial_available=video_trial, quiz_trial_available=quiz_trial
        ),
    )


_LESSON_STATUS_TO_CELERY: dict[LessonStatus, str] = {
    LessonStatus.draft: "PENDING",
    LessonStatus.analyzing: "PROGRESS",
    LessonStatus.ready_for_edit: "PENDING",
    LessonStatus.processing: "PROGRESS",
    LessonStatus.published: "SUCCESS",
    LessonStatus.error: "FAILURE",
    LessonStatus.cancelled: "REVOKED",
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

    if lesson.status == LessonStatus.cancelled:
        payload["meta"] = {"credits_spent": lesson.credits_spent}
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


_SSE_TERMINAL = {"published", "ready_for_edit", "error", "cancelled"}


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
    # Only when NO task is active — both pipelines clear their *_task_id on finish, so a
    # set task_id means a job is queued/running (e.g. a regeneration whose status still
    # reads as the prior run's `published`). Replaying that stale terminal would make the
    # client think the new job already finished and hide the live pipeline until reload.
    has_active_task = lesson.video_task_id is not None or lesson.analyze_task_id is not None
    terminal_payload: dict | None = None
    if not has_active_task:
        if lesson.status == LessonStatus.published:
            terminal_payload = {"status": "published", "video_url": lesson.video_url}
        elif lesson.status == LessonStatus.error:
            terminal_payload = {"status": "error"}
        elif lesson.status == LessonStatus.ready_for_edit:
            terminal_payload = {"status": "ready_for_edit"}
        elif lesson.status == LessonStatus.cancelled:
            terminal_payload = {"status": "cancelled", "credits_spent": lesson.credits_spent}

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


@router.post("/{lesson_id}/publish", response_model=LessonOut)
async def publish_lesson(
    lesson_id: UUID,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    """Publish a lesson. Independent of course/module flags; idempotent."""
    if not lesson.is_published:
        lesson.is_published = True
        await db.commit()
        await db.refresh(lesson)
    return _lesson_out(lesson, str(user.id))


@router.post("/{lesson_id}/unpublish", response_model=LessonOut)
async def unpublish_lesson(
    lesson_id: UUID,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    """Unpublish a lesson. Idempotent; hiding from students is the read-time
    AND in visibility_service, so nothing cascades."""
    if lesson.is_published:
        lesson.is_published = False
        await db.commit()
        await db.refresh(lesson)
    return _lesson_out(lesson, str(user.id))


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


def _relative_video_path(stored_url: str | None) -> str:
    """Storage key of a lesson video, or 404 when absent / unrecognised. Confined
    to the ``videos/`` prefix so this endpoint can never be coerced into reading
    other stored objects."""
    relative = storage_service.relative_path_from_url(stored_url)
    if not relative or not relative.startswith("videos/"):
        raise HTTPException(status_code=404, detail="Video not found")
    return relative


def _stream_video_response(relative: str, user_id: str) -> Response:
    """Deliver a lesson MP4 to an already-authorised caller. The access guard has
    run; this only chooses HOW the bytes reach the client, always keeping the byte
    transfer out of the Python process AND off the same-origin proxy:

    * S3 (primary): 302 to a short-lived presigned URL — the browser streams
      straight from S3, which serves Range/seek. Within S3_PRESIGN_TTL_SECONDS
      that URL is a bearer capability (see constants.py).
    * local + nginx: empty body + X-Accel-Redirect to the internal
      /protected-media/ location; nginx serves the file (Range/sendfile) and the
      absolute FS path never leaves the server — nginx strips the header, so the
      client never sees it.
    * local + no nginx (dev): 302 to a signed absolute /files/* URL. The browser
      then fetches bytes DIRECTLY from the backend (Range/seek) — NOT a
      FileResponse streamed back through the Nuxt dev proxy, which hangs relaying
      a 206. Bearer-signed with SIGNED_URL_TTL_VIDEO, the same model as covers;
      dev-only (the /files/videos/* path is closed in prod — see files.py).
    """
    if settings.STORAGE_BACKEND == "s3":
        if not settings.S3_BUCKET_NAME:
            logger.error("video_stream_s3_misconfigured", relative=relative)
            raise HTTPException(status_code=500, detail="Storage backend misconfigured")
        url = storage_service.presign_stream_url(relative, S3_PRESIGN_TTL_SECONDS)
        # no-store so no shared/CDN/proxy cache can retain this 302 and hand the
        # presigned URL — a bearer capability for its TTL — to another student.
        return RedirectResponse(
            url=url, status_code=302, headers={"Cache-Control": "no-store"}
        )

    if not storage_service.exists(relative):
        raise HTTPException(status_code=404, detail="Video not found")

    if VIDEO_XACCEL_ENABLED:
        content_type = mimetypes.guess_type(relative)[0] or "video/mp4"
        # quote() so a filename with spaces/unicode yields a valid internal URI;
        # nginx URL-decodes it back against the /protected-media/ alias.
        internal_uri = f"{VIDEO_XACCEL_INTERNAL_PREFIX}{quote(relative, safe='/')}"
        return Response(
            status_code=200,
            headers={"X-Accel-Redirect": internal_uri, "Content-Type": content_type},
        )

    signed = storage_service.get_url(relative, user_id, expires_in=SIGNED_URL_TTL_VIDEO)
    return RedirectResponse(
        url=signed, status_code=302, headers={"Cache-Control": "no-store"}
    )


@router.get("/{lesson_id}/video/stream")
async def stream_lesson_video(
    access: tuple[User, Lesson, bool] = Depends(require_lesson_access),
) -> Response:
    """Authorised stream of a lesson's current video (the student player source).
    Access — teacher-owner or enrolled student with the module/lesson published —
    is enforced by require_lesson_access before any bytes or redirect are produced
    (missing/hidden lesson → 404, non-enrolled → 403)."""
    user, lesson, _is_owner = access
    relative = _relative_video_path(lesson.video_url)
    return _stream_video_response(relative, str(user.id))


@router.get("/{lesson_id}/videos/{video_id}/stream")
async def stream_lesson_video_render(
    video_id: UUID,
    access: tuple[User, Lesson, bool] = Depends(require_lesson_access),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Authorised stream of one specific render. Owners may stream any render; an
    enrolled student may stream only a published one — a draft render 404s, never
    revealing that an unpublished render exists."""
    user, lesson, is_owner = access
    video = await db.scalar(
        select(LessonVideo).where(
            LessonVideo.id == video_id, LessonVideo.lesson_id == lesson.id
        )
    )
    if video is None or (not is_owner and not video.is_published):
        raise HTTPException(status_code=404, detail="Video not found")
    relative = _relative_video_path(video.video_url)
    return _stream_video_response(relative, str(user.id))
