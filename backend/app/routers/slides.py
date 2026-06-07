import structlog
from uuid import UUID

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.constants import CREDIT_WEIGHTS
from app.database import get_db
from app.dependencies import get_owned_lesson, require_teacher, require_verified_teacher
from app.limiter import limiter
from app.models.credit import CreditOperation
from app.models.lesson import CreationMode, Lesson, LessonStatus
from app.models.slide_text import SlideText
from app.models.user import User
from app.services import billing_service
from app.schemas.slide import (
    AnalyzeStatusResponse,
    SlideListResponse,
    SlideTextOut,
    SlideTextUpdate,
)
from app.config import settings
from app.services.llm_service import llm_service
from app.services.storage_service import storage_service
from app.services.vision_analysis import vision_analysis_service
from app.tasks.vision_pipeline import analyze_presentation_task

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/lessons", tags=["slides"])


def _row_to_out(row: SlideText, user_id: str) -> SlideTextOut:
    image_url: str | None = None
    if row.image_path:
        image_url = storage_service.get_url(row.image_path, user_id)
    return SlideTextOut(
        id=row.id,
        slide_number=row.slide_number,
        image_url=image_url,
        image_path=row.image_path,
        generated_text=row.generated_text or "",
        edited_text=row.edited_text,
        is_edited=bool(row.edited_text and row.edited_text.strip()),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# TODO: в тестах сбрасывать лимитер через limiter.reset() или MemoryStorage в фикстуре
@router.post("/{lesson_id}/analyze")
@limiter.limit("2/minute")
async def analyze_lesson_slides(
    request: Request,
    lesson_id: UUID,
    _verified: User = Depends(require_verified_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    if not lesson.pptx_path:
        raise HTTPException(
            status_code=400,
            detail="Загрузите PPTX перед анализом презентации",
        )

    lesson.creation_mode = CreationMode.presentation_auto
    lesson.status = LessonStatus.analyzing
    await db.commit()

    task = analyze_presentation_task.apply_async(
        args=[str(lesson.id), lesson.pptx_path], queue="vision"
    )
    lesson.analyze_task_id = task.id
    await db.commit()
    return {"task_id": task.id, "lesson_id": str(lesson.id), "status": "analyzing"}


@router.post("/{lesson_id}/analysis-cancel")
async def cancel_analysis(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    if lesson.status != LessonStatus.analyzing:
        raise HTTPException(status_code=400, detail="Lesson is not being analyzed")

    if lesson.analyze_task_id:
        celery_app.control.revoke(lesson.analyze_task_id, terminate=True, signal="SIGTERM")

    lesson.status = LessonStatus.draft
    lesson.analyze_task_id = None
    await db.commit()

    # A terminated task's `finally` block may not run, so its reserved credit
    # hold would leak. Release it idempotently (no-op if the task already
    # finalized before the revoke landed).
    owner_id = lesson.module.course.owner_id
    await billing_service.release_reservation_if_held(db, owner_id, str(lesson_id))
    return {"ok": True}


@router.get(
    "/{lesson_id}/analysis-status/{task_id}",
    response_model=AnalyzeStatusResponse,
)
async def analysis_status(
    lesson_id: UUID,
    task_id: str,
    _lesson: Lesson = Depends(get_owned_lesson),
):
    result = AsyncResult(task_id, app=celery_app)

    payload: dict = {"status": result.status, "task_id": task_id}
    if result.state == "PROGRESS":
        info = result.info or {}
        payload.update(
            {
                "step": info.get("step"),
                "done": info.get("done"),
                "total": info.get("total"),
            }
        )
    elif result.ready():
        if result.failed():
            payload["error"] = (
                str(result.result) if result.result is not None else "Analysis failed"
            )  # noqa: E501
            payload["traceback"] = result.traceback
        elif isinstance(result.result, dict):
            err = result.result.get("error")
            if err:
                payload["error"] = err

    return payload


@router.get("/{lesson_id}/slides", response_model=SlideListResponse)
async def list_slides(
    lesson_id: UUID,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    rows_q = await db.execute(
        select(SlideText).where(SlideText.lesson_id == lesson_id).order_by(SlideText.slide_number)
    )
    rows = list(rows_q.scalars())
    return SlideListResponse(
        lesson_id=lesson_id,
        status=lesson.status.value if hasattr(lesson.status, "value") else str(lesson.status),
        total=len(rows),
        slides=[_row_to_out(r, str(user.id)) for r in rows],
    )


@router.patch("/{lesson_id}/slides/{slide_id}", response_model=SlideTextOut)
async def update_slide_text(
    lesson_id: UUID,
    slide_id: UUID,
    data: SlideTextUpdate,
    user: User = Depends(require_teacher),
    _lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(SlideText, slide_id)
    if not row or row.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="Slide not found")

    row.edited_text = data.edited_text
    await db.commit()
    await db.refresh(row)
    return _row_to_out(row, str(user.id))


@router.post("/{lesson_id}/slides/{slide_id}/regenerate", response_model=SlideTextOut)
async def regenerate_slide_text(
    lesson_id: UUID,
    slide_id: UUID,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    row = await db.get(SlideText, slide_id)
    if not row or row.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="Slide not found")
    if not row.image_path:
        raise HTTPException(
            status_code=400, detail="У слайда нет изображения для повторного анализа"
        )

    # Sibling slides for accumulated context (last 3 before current).
    siblings_q = await db.execute(
        select(SlideText)
        .where(SlideText.lesson_id == lesson_id)
        .where(SlideText.slide_number < row.slide_number)
        .order_by(SlideText.slide_number.desc())
        .limit(3)
    )
    siblings = list(reversed(list(siblings_q.scalars())))
    context_lines = []
    for s in siblings:
        text = (s.edited_text or s.generated_text or "").strip()
        if text:
            cleaned = " ".join(text.split())[:280]
            context_lines.append(f"Слайд {s.slide_number}: {cleaned}")
    previous_context = "\n".join(context_lines)

    total_q = await db.execute(select(SlideText).where(SlideText.lesson_id == lesson_id))
    total = len(list(total_q.scalars()))

    amount = CREDIT_WEIGHTS["slide_regen"]
    ok = await billing_service.reserve_credits(
        db, user.id, amount, str(slide_id), CreditOperation.SLIDE_REGEN
    )
    if not ok:
        raise HTTPException(status_code=402, detail="Недостаточно кредитов")

    image_full_path = storage_service.get_full_path(row.image_path)
    try:
        # Phase 1: vision model (VISION_MODEL) extracts narration from the slide image.
        # Phase 2: text LLM (REGEN_LLM_MODEL = qwen3:8b) polishes the raw vision output.
        # Two phases because analyze_slide is vision-only — there is no text-LLM pass
        # inside the standard vision pipeline that we could redirect.
        vision_text = await vision_analysis_service.analyze_slide(
            slide_image_path=image_full_path,
            slide_number=row.slide_number,
            total_slides=total,
            course_title=lesson.title or "",
            previous_context=previous_context,
        )
        text = await llm_service.refine_slide_narration(
            vision_text, model=settings.REGEN_LLM_MODEL
        )
    except Exception as exc:
        await billing_service.release_credits(db, user.id, amount, str(slide_id))
        logger.exception("slide_regen_failed", slide_id=str(slide_id))
        raise HTTPException(status_code=500, detail=f"Ошибка LLM: {exc}")

    row.generated_text = text or ""
    row.edited_text = None
    await db.commit()
    await db.refresh(row)
    await billing_service.charge_credits(
        db, user.id, amount, str(slide_id), CreditOperation.SLIDE_REGEN
    )
    return _row_to_out(row, str(user.id))
