"""Lesson knowledge base: supplementary materials (files) + markdown notes.

One router for both roles, mirroring routers/comments.py:
  * reads go through `require_lesson_access` — teacher-owner or enrolled student,
    with a draft lesson hidden as 404 (never 403) by the shared visibility rule;
  * writes are nested under the same `/lessons/{lesson_id}/…` prefix and depend
    on `get_owned_lesson`, so ownership is enforced by the dependency and never
    re-derived here.

No LLM/TTS/vision and no credits are involved — hand-authored content only —
so these endpoints are deliberately NOT in AI_GATED_ENDPOINTS and sit behind
plain `require_teacher` (via get_owned_lesson), exactly like lesson/quiz/
assignment authoring CRUD.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_owned_lesson, require_lesson_access, require_teacher
from app.limiter import limiter
from app.models.lesson import Lesson
from app.models.user import User
from app.schemas.lesson_material import (
    KnowledgeBaseRead,
    MaterialRead,
    MaterialUpdate,
    NoteCreate,
    NoteRead,
    NotesReorder,
    NoteUpdate,
)
from app.services import lesson_material_service

router = APIRouter(prefix="/api/v1", tags=["lesson-knowledge"])


@router.get("/lessons/{lesson_id}/knowledge", response_model=KnowledgeBaseRead)
async def get_lesson_knowledge(
    lesson_id: UUID,
    access: tuple[User, Lesson, bool] = Depends(require_lesson_access),
    db: AsyncSession = Depends(get_db),
) -> KnowledgeBaseRead:
    user, _lesson, is_owner = access
    return await lesson_material_service.get_knowledge_base(
        db, lesson_id, viewer_id=str(user.id), can_edit=is_owner
    )


# ── Materials (teacher-owner only) ───────────────────────────────────────────


@router.post(
    "/lessons/{lesson_id}/materials",
    response_model=MaterialRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def upload_lesson_material(
    request: Request,
    file: UploadFile,
    title: str | None = Form(default=None),
    description: str | None = Form(default=None),
    lesson: Lesson = Depends(get_owned_lesson),
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> MaterialRead:
    material = await lesson_material_service.add_material(
        db,
        lesson_id=lesson.id,
        uploaded_by=user.id,
        file=file,
        title=title,
        description=description,
    )
    return lesson_material_service.serialize_material(material, str(user.id))


@router.patch("/lessons/{lesson_id}/materials/{material_id}", response_model=MaterialRead)
async def update_lesson_material(
    material_id: UUID,
    data: MaterialUpdate,
    lesson: Lesson = Depends(get_owned_lesson),
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> MaterialRead:
    material = await lesson_material_service.update_material(
        db,
        lesson_id=lesson.id,
        material_id=material_id,
        updates=data.model_dump(exclude_unset=True),
    )
    return lesson_material_service.serialize_material(material, str(user.id))


@router.delete(
    "/lessons/{lesson_id}/materials/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_lesson_material(
    material_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await lesson_material_service.delete_material(db, lesson_id=lesson.id, material_id=material_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Notes (teacher-owner only) ───────────────────────────────────────────────


@router.post(
    "/lessons/{lesson_id}/notes",
    response_model=NoteRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("60/minute")
async def create_lesson_note(
    request: Request,
    data: NoteCreate,
    lesson: Lesson = Depends(get_owned_lesson),
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> NoteRead:
    note = await lesson_material_service.create_note(
        db, lesson_id=lesson.id, created_by=user.id, data=data
    )
    return NoteRead.model_validate(note)


@router.patch("/lessons/{lesson_id}/notes/{note_id}", response_model=NoteRead)
@limiter.limit("60/minute")
async def update_lesson_note(
    request: Request,
    note_id: UUID,
    data: NoteUpdate,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> NoteRead:
    note = await lesson_material_service.update_note(
        db,
        lesson_id=lesson.id,
        note_id=note_id,
        updates=data.model_dump(exclude_unset=True),
    )
    return NoteRead.model_validate(note)


@router.delete("/lessons/{lesson_id}/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lesson_note(
    note_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await lesson_material_service.delete_note(db, lesson_id=lesson.id, note_id=note_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/lessons/{lesson_id}/notes/order", response_model=list[NoteRead])
async def reorder_lesson_notes(
    data: NotesReorder,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> list[NoteRead]:
    notes = await lesson_material_service.reorder_notes(
        db, lesson_id=lesson.id, note_ids=data.note_ids
    )
    return [NoteRead.model_validate(n) for n in notes]
