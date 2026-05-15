from uuid import UUID

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.database import get_db
from app.dependencies import get_owned_lesson, require_teacher
from app.models.course import Course
from app.models.lesson import Lesson, LessonStatus, Module
from app.models.user import User
from app.schemas.lesson import (
    LessonCreate,
    LessonOut,
    LessonUpdate,
    ScriptUpdateRequest,
    TaskStatusResponse,
    VideoGenerateRequest,
)
from app.services.storage_service import storage_service
from app.tasks.video_pipeline import generate_video_lesson


def _lesson_out(lesson: Lesson, user_id: str) -> LessonOut:
    out = LessonOut.model_validate(lesson)
    out.video_url = storage_service.resign_url(out.video_url, user_id)
    return out

router = APIRouter(prefix="/api/v1/lessons", tags=["lessons"])



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
):
    return _lesson_out(lesson, str(user.id))


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


@router.post("/{lesson_id}/generate-video")
async def generate_video(
    lesson_id: UUID,
    data: VideoGenerateRequest,
    user: User = Depends(require_teacher),
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
):
    pptx_path = data.pptx_path or lesson.pptx_path
    if not pptx_path:
        raise HTTPException(
            status_code=400,
            detail="pptx_path is required (pass it in the body or upload a PPTX to the lesson first)",
        )

    # Persist pptx_path on the lesson so it can be reused on retries
    if data.pptx_path and data.pptx_path != lesson.pptx_path:
        lesson.pptx_path = data.pptx_path
        await db.commit()

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

    from app.models.lesson import LessonStatus
    if lesson.creation_mode and str(lesson.creation_mode) in ("presentation_auto",):
        lesson.status = LessonStatus.ready_for_edit
    else:
        lesson.status = LessonStatus.draft
    await db.commit()
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
        payload["result"] = {"video_url": lesson.video_url}
        return payload

    if lesson.status == LessonStatus.error:
        payload["error"] = "Video generation failed"
        return payload

    # Try Redis for live progress details; fails gracefully if Redis is down.
    try:
        ar = AsyncResult(task_id, app=celery_app)
        if ar.state == "PROGRESS" and isinstance(ar.info, dict):
            payload["meta"] = ar.info
            done = ar.info.get("done", 0)
            total = ar.info.get("total", 1) or 1
            payload["progress_pct"] = round(done / total * 100)
    except Exception:
        pass

    return payload
