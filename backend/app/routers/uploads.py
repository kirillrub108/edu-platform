import os
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_teacher
from app.models.lesson import Lesson
from app.models.user import User
from app.services.storage_service import storage_service

router = APIRouter(prefix="/api/v1/uploads", tags=["uploads"])

ALLOWED_PPTX = {".pptx", ".ppt", ".pdf"}
ALLOWED_VIDEO = {".mp4", ".webm", ".mov"}


def _ext_ok(filename: str | None, allowed: set[str]) -> bool:
    if not filename:
        return False
    return os.path.splitext(filename)[1].lower() in allowed


@router.post("/pptx")
async def upload_pptx(
    file: UploadFile,
    lesson_id: UUID | None = None,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
):
    if not _ext_ok(file.filename, ALLOWED_PPTX):
        raise HTTPException(status_code=400, detail="Only PPTX/PPT/PDF allowed")

    relative = await storage_service.save_upload(file, "pptx")

    # Optionally attach the uploaded file to a lesson right away
    if lesson_id is not None:
        lesson = await db.get(Lesson, lesson_id)
        if lesson is None:
            raise HTTPException(status_code=404, detail="Lesson not found")
        lesson.pptx_path = relative
        await db.commit()

    return {
        "file_path": relative,
        "file_url": storage_service.get_url(relative),
    }


@router.post("/video")
async def upload_video(
    file: UploadFile,
    user: User = Depends(require_teacher),
):
    if not _ext_ok(file.filename, ALLOWED_VIDEO):
        raise HTTPException(status_code=400, detail="Only MP4/WebM/MOV allowed")
    relative = await storage_service.save_upload(file, "videos")
    return {
        "file_path": relative,
        "file_url": storage_service.get_url(relative),
    }
