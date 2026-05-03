from uuid import UUID

from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.celery_app import celery_app
from app.database import get_db
from app.dependencies import require_teacher
from app.models.course import Course
from app.models.lesson import Lesson, Module
from app.models.user import User
from app.schemas.lesson import (
    LessonCreate,
    LessonOut,
    LessonUpdate,
    ScriptUpdateRequest,
    TaskStatusResponse,
    VideoGenerateRequest,
)
from app.tasks.video_pipeline import generate_video_lesson

router = APIRouter(prefix="/api/v1/lessons", tags=["lessons"])


async def _get_owned_lesson(lesson_id: UUID, user: User, db: AsyncSession) -> Lesson:
    lesson = await db.get(Lesson, lesson_id)
    if not lesson:
        raise HTTPException(status_code=404, detail="Lesson not found")
    module = await db.get(Module, lesson.module_id)
    course = await db.get(Course, module.course_id)
    if course.owner_id != user.id:
        raise HTTPException(status_code=403, detail="Not your lesson")
    return lesson


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
    )
    db.add(lesson)
    await db.commit()
    await db.refresh(lesson)
    return lesson


@router.get("/{lesson_id}", response_model=LessonOut)
async def get_lesson(
    lesson_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    return await _get_owned_lesson(lesson_id, user, db)


@router.put("/{lesson_id}", response_model=LessonOut)
async def update_lesson(
    lesson_id: UUID,
    data: LessonUpdate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    lesson = await _get_owned_lesson(lesson_id, user, db)
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(lesson, key, value)
    await db.commit()
    await db.refresh(lesson)
    return lesson


@router.delete("/{lesson_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson(
    lesson_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    lesson = await _get_owned_lesson(lesson_id, user, db)
    await db.delete(lesson)
    await db.commit()


@router.put("/{lesson_id}/script", response_model=LessonOut)
async def update_script(
    lesson_id: UUID,
    data: ScriptUpdateRequest,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    lesson = await _get_owned_lesson(lesson_id, user, db)
    lesson.script = data.script
    await db.commit()
    await db.refresh(lesson)
    return lesson


@router.post("/{lesson_id}/generate-video")
async def generate_video(
    lesson_id: UUID,
    data: VideoGenerateRequest,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    lesson = await _get_owned_lesson(lesson_id, user, db)

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

    task = generate_video_lesson.delay(str(lesson.id), pptx_path, data.voice)
    return {"task_id": task.id, "lesson_id": str(lesson.id)}


@router.get("/{lesson_id}/task-status/{task_id}", response_model=TaskStatusResponse)
async def task_status(
    lesson_id: UUID,
    task_id: str,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_lesson(lesson_id, user, db)
    result = AsyncResult(task_id, app=celery_app)

    payload: dict = {"task_id": task_id, "status": result.status, "result": None, "meta": None}

    if result.state == "PROGRESS":
        payload["meta"] = result.info  # {"step": ..., "done": ..., "total": ...}
    elif result.ready():
        try:
            payload["result"] = result.result if isinstance(result.result, dict) else {"value": str(result.result)}
        except Exception:
            payload["result"] = None

    return payload
