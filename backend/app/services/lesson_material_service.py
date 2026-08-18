"""Lesson knowledge base: teacher-attached materials (files) + markdown notes.

Synchronous (request/response) — no Celery, no LLM/TTS/vision, no credits. Files
are only STORED, never parsed server-side (same contract as assignment
attachments: extension whitelist → MIME, magic bytes, zip-slip/zip-bomb checks).

Ownership and student visibility are NOT re-derived here — the router passes an
already-authorized lesson (`get_owned_lesson` for writes, `require_lesson_access`
for reads), so this module only enforces resource scoping (the row must belong to
the given lesson) and the quota/whitelist policy.
"""

from __future__ import annotations

import os
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    LESSON_MATERIAL_ALLOWED_TYPES,
    LESSON_MATERIAL_CATEGORY_MAX_SIZE_MB,
    LESSON_MATERIAL_EXTENSION_MIME,
    LESSON_MATERIAL_MAX_FILES,
    LESSON_MATERIAL_MAX_TOTAL_SIZE_MB,
    LESSON_NOTE_MAX_PER_LESSON,
    SIGNED_URL_TTL_MATERIAL,
)
from app.models.lesson_material import LessonMaterial, LessonNote
from app.schemas.lesson_material import (
    KnowledgeBaseRead,
    KnowledgeLimits,
    MaterialRead,
    NoteCreate,
    NoteRead,
)
from app.services.file_validation_service import validate_upload
from app.services.storage_service import UploadTooLargeError, storage_service

# Storage prefix for every material of a lesson. Defined here because the purge
# pipeline deletes this same prefix when a lesson is hard-deleted.
MATERIAL_SUBFOLDER = "materials"


def material_prefix(lesson_id: UUID | str) -> str:
    return f"{MATERIAL_SUBFOLDER}/{lesson_id}"


# ── Serialization ────────────────────────────────────────────────────────────


def serialize_material(material: LessonMaterial, viewer_id: str) -> MaterialRead:
    """Relative storage path → a fresh download URL: HMAC-signed /files link on
    the local backend, presigned object URL on S3 (storage_service picks)."""
    return MaterialRead(
        id=material.id,
        lesson_id=material.lesson_id,
        title=material.title,
        description=material.description,
        original_filename=material.original_filename,
        content_type=material.content_type,
        size_bytes=material.size_bytes,
        uploaded_by=material.uploaded_by,
        created_at=material.created_at,
        updated_at=material.updated_at,
        download_url=storage_service.get_url(
            material.file_path, viewer_id, expires_in=SIGNED_URL_TTL_MATERIAL
        ),
    )


def _limits() -> KnowledgeLimits:
    return KnowledgeLimits(allowed_ext=sorted(LESSON_MATERIAL_EXTENSION_MIME))


async def get_knowledge_base(
    db: AsyncSession, lesson_id: UUID, *, viewer_id: str, can_edit: bool
) -> KnowledgeBaseRead:
    materials = await list_materials(db, lesson_id)
    notes = await list_notes(db, lesson_id)
    return KnowledgeBaseRead(
        materials=[serialize_material(m, viewer_id) for m in materials],
        notes=[NoteRead.model_validate(n) for n in notes],
        can_edit=can_edit,
        limits=_limits(),
    )


# ── Materials ────────────────────────────────────────────────────────────────


async def list_materials(db: AsyncSession, lesson_id: UUID) -> list[LessonMaterial]:
    result = await db.execute(
        select(LessonMaterial)
        .where(LessonMaterial.lesson_id == lesson_id)
        .order_by(LessonMaterial.created_at)
    )
    return list(result.scalars().all())


async def get_material(db: AsyncSession, lesson_id: UUID, material_id: UUID) -> LessonMaterial:
    material = await db.get(LessonMaterial, material_id)
    # The scope check doubles as the not-found response: a material belonging to
    # another lesson is indistinguishable from one that never existed.
    if material is None or material.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="Material not found")
    return material


def _resolve_category(file: UploadFile) -> tuple[str, str]:
    """Return (category, ext) for an upload, by MIME with an extension fallback.

    The extension MUST be on the whitelist even when the MIME already resolves —
    this rejects a forged Content-Type riding on a disallowed extension.
    """
    ext = os.path.splitext(file.filename or "")[1].lower().lstrip(".")
    ext_mime = LESSON_MATERIAL_EXTENSION_MIME.get(ext)
    if ext_mime is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "extension_not_allowed",
                "message": f"Тип файла «{file.filename or ext or 'неизвестно'}» не поддерживается.",
            },
        )
    mime = (file.content_type or "").split(";")[0].strip().lower()
    category = LESSON_MATERIAL_ALLOWED_TYPES.get(mime) or LESSON_MATERIAL_ALLOWED_TYPES[ext_mime]
    return category, ext


def _too_large(
    filename: str | None, category: str, cat_limit_bytes: int, *, over_total: bool
) -> HTTPException:
    if over_total:
        return HTTPException(
            status_code=400,
            detail={
                "code": "materials_too_large",
                "max_total_mb": LESSON_MATERIAL_MAX_TOTAL_SIZE_MB,
                "message": (
                    f"Суммарный объём материалов урока превышает лимит "
                    f"{LESSON_MATERIAL_MAX_TOTAL_SIZE_MB} МБ."
                ),
            },
        )
    cat_mb = cat_limit_bytes // (1024 * 1024)
    return HTTPException(
        status_code=400,
        detail={
            "code": "file_too_large",
            "category": category,
            "max_file_mb": cat_mb,
            "message": (
                f"Файл «{filename}» превышает лимит {cat_mb} МБ для категории «{category}»."
            ),
        },
    )


async def add_material(
    db: AsyncSession,
    *,
    lesson_id: UUID,
    uploaded_by: UUID,
    file: UploadFile,
    title: str | None,
    description: str | None,
) -> LessonMaterial:
    existing = await list_materials(db, lesson_id)
    if len(existing) >= LESSON_MATERIAL_MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "too_many_files",
                "max_files": LESSON_MATERIAL_MAX_FILES,
                "message": (
                    f"Слишком много материалов: не более {LESSON_MATERIAL_MAX_FILES} на урок."
                ),
            },
        )

    category, ext = _resolve_category(file)
    cat_limit_bytes = LESSON_MATERIAL_CATEGORY_MAX_SIZE_MB[category] * 1024 * 1024
    used_bytes = sum(m.size_bytes for m in existing)
    remaining_total_bytes = LESSON_MATERIAL_MAX_TOTAL_SIZE_MB * 1024 * 1024 - used_bytes
    hard_cap = min(cat_limit_bytes, remaining_total_bytes)

    # Pre-flight: `file.size` is the exact byte count the multipart parser
    # buffered — reject an obvious overflow before any permanent write.
    if file.size is not None and file.size > hard_cap:
        raise _too_large(
            file.filename,
            category,
            cat_limit_bytes,
            over_total=remaining_total_bytes < cat_limit_bytes,
        )

    # Deep safety: magic-byte + zip-bomb/zip-slip checks (no XML parsing). Size
    # is governed by the streaming hard cap below, so SIZE_LIMITS is skipped.
    await validate_upload(file, [f".{ext}"], enforce_size_limits=False)

    try:
        relative, written = await storage_service.save_upload_bounded(
            file, material_prefix(lesson_id), hard_cap
        )
    except UploadTooLargeError:
        # Reached only when the declared size was absent or understated.
        raise _too_large(
            file.filename,
            category,
            cat_limit_bytes,
            over_total=remaining_total_bytes < cat_limit_bytes,
        )

    material = LessonMaterial(
        lesson_id=lesson_id,
        title=(title or "").strip() or (file.filename or f"file.{ext}"),
        description=(description or "").strip() or None,
        file_path=relative,
        original_filename=file.filename or f"file.{ext}",
        content_type=file.content_type,
        size_bytes=written,
        uploaded_by=uploaded_by,
    )
    db.add(material)
    await db.commit()
    await db.refresh(material)
    return material


async def update_material(
    db: AsyncSession, *, lesson_id: UUID, material_id: UUID, updates: dict[str, object]
) -> LessonMaterial:
    material = await get_material(db, lesson_id, material_id)
    for field, value in updates.items():
        setattr(material, field, value)
    await db.commit()
    await db.refresh(material)
    return material


async def delete_material(db: AsyncSession, *, lesson_id: UUID, material_id: UUID) -> None:
    """Remove the stored object first, then the row. A crash between the two
    leaves an orphan file (reclaimed by the lesson-prefix purge) rather than a
    row pointing at bytes that no longer exist."""
    material = await get_material(db, lesson_id, material_id)
    storage_service.delete_file(material.file_path)
    await db.delete(material)
    await db.commit()


# ── Notes ────────────────────────────────────────────────────────────────────


async def list_notes(db: AsyncSession, lesson_id: UUID) -> list[LessonNote]:
    result = await db.execute(
        select(LessonNote)
        .where(LessonNote.lesson_id == lesson_id)
        .order_by(LessonNote.order, LessonNote.created_at)
    )
    return list(result.scalars().all())


async def get_note(db: AsyncSession, lesson_id: UUID, note_id: UUID) -> LessonNote:
    note = await db.get(LessonNote, note_id)
    if note is None or note.lesson_id != lesson_id:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


async def create_note(
    db: AsyncSession, *, lesson_id: UUID, created_by: UUID, data: NoteCreate
) -> LessonNote:
    count = await db.scalar(
        select(func.count()).select_from(LessonNote).where(LessonNote.lesson_id == lesson_id)
    )
    if int(count or 0) >= LESSON_NOTE_MAX_PER_LESSON:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "too_many_notes",
                "max_notes": LESSON_NOTE_MAX_PER_LESSON,
                "message": (
                    f"Слишком много конспектов: не более {LESSON_NOTE_MAX_PER_LESSON} на урок."
                ),
            },
        )
    max_order = await db.scalar(
        select(func.max(LessonNote.order)).where(LessonNote.lesson_id == lesson_id)
    )
    note = LessonNote(
        lesson_id=lesson_id,
        title=data.title,
        content=data.content,
        order=0 if max_order is None else int(max_order) + 1,
        created_by=created_by,
    )
    db.add(note)
    await db.commit()
    await db.refresh(note)
    return note


async def update_note(
    db: AsyncSession, *, lesson_id: UUID, note_id: UUID, updates: dict[str, object]
) -> LessonNote:
    note = await get_note(db, lesson_id, note_id)
    for field, value in updates.items():
        setattr(note, field, value)
    await db.commit()
    await db.refresh(note)
    return note


async def delete_note(db: AsyncSession, *, lesson_id: UUID, note_id: UUID) -> None:
    note = await get_note(db, lesson_id, note_id)
    await db.delete(note)
    await db.commit()


async def reorder_notes(
    db: AsyncSession, *, lesson_id: UUID, note_ids: list[UUID]
) -> list[LessonNote]:
    """Rewrite `order` from the given sequence. The list must be exactly the
    lesson's notes — a partial or foreign list is rejected rather than silently
    applied, so the resulting order stays dense and unambiguous."""
    notes = await list_notes(db, lesson_id)
    if len(note_ids) != len(set(note_ids)) or set(note_ids) != {n.id for n in notes}:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_note_order",
                "message": "Список должен содержать все конспекты урока ровно по одному разу.",
            },
        )
    position = {note_id: idx for idx, note_id in enumerate(note_ids)}
    for note in notes:
        note.order = position[note.id]
    await db.commit()
    return await list_notes(db, lesson_id)
