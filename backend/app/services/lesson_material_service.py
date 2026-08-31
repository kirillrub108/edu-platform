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
import re
from uuid import UUID

import structlog
from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import (
    LESSON_MATERIAL_ALLOWED_TYPES,
    LESSON_MATERIAL_CATEGORY_MAX_SIZE_MB,
    LESSON_MATERIAL_EXTENSION_MIME,
    LESSON_MATERIAL_MAX_FILES,
    LESSON_MATERIAL_MAX_INLINE_FILES,
    LESSON_MATERIAL_MAX_TOTAL_SIZE_MB,
    LESSON_NOTE_MAX_PER_LESSON,
    SIGNED_URL_TTL_MATERIAL,
)
from app.models.course import Course
from app.models.lesson import Lesson, Module
from app.models.lesson_material import LessonMaterial, LessonNote
from app.schemas.lesson_material import (
    CourseKnowledgeLessonRead,
    CourseKnowledgeModuleRead,
    CourseKnowledgeNoteRead,
    CourseKnowledgeTreeRead,
    KnowledgeBaseRead,
    KnowledgeLimits,
    MaterialRead,
    NoteCreate,
    NoteRead,
)
from app.services import visibility_service
from app.services.file_validation_service import validate_upload
from app.services.storage_service import UploadTooLargeError, storage_service

log = structlog.get_logger(__name__)

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
        is_inline=material.is_inline,
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
    is_inline: bool = False,
) -> LessonMaterial:
    existing = await list_materials(db, lesson_id)
    inline_count = sum(1 for m in existing if m.is_inline)
    if len(existing) >= LESSON_MATERIAL_MAX_FILES:
        # Inline attachments are hidden from the «Файлы» list but still consume
        # this quota, so the message spells out that share — otherwise the
        # teacher sees a full lesson with a visibly short list of files.
        raise HTTPException(
            status_code=400,
            detail={
                "code": "too_many_files",
                "max_files": LESSON_MATERIAL_MAX_FILES,
                "inline_files": inline_count,
                "message": (
                    f"Слишком много материалов: не более {LESSON_MATERIAL_MAX_FILES} "
                    f"на урок (сейчас {len(existing)}, из них {inline_count} — "
                    f"вложения в тексте урока)."
                ),
            },
        )
    # Sub-cap inside the lesson-wide ceiling above, not a parallel budget.
    if is_inline and inline_count >= LESSON_MATERIAL_MAX_INLINE_FILES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "too_many_inline_files",
                "max_inline_files": LESSON_MATERIAL_MAX_INLINE_FILES,
                "message": (
                    f"Слишком много вложений в тексте: не более "
                    f"{LESSON_MATERIAL_MAX_INLINE_FILES} на урок."
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
        is_inline=is_inline,
        uploaded_by=uploaded_by,
    )
    db.add(material)
    await db.commit()
    await db.refresh(material)
    return material


async def register_uploaded_file(
    db: AsyncSession,
    *,
    lesson_id: UUID,
    uploaded_by: UUID,
    file: UploadFile,
) -> LessonMaterial | None:
    """Mirror a file uploaded through /uploads/* into the lesson's knowledge base.

    NEVER raises: the caller's primary outcome (PPTX attached / script text
    extracted) must succeed even when the material cannot be registered — an
    exhausted quota or an extension outside the material whitelist is a skip
    with a log line, not a failed upload.

    Stores its OWN copy under `materials/{lesson_id}/` rather than pointing at
    the pipeline's object: sharing would make "delete this material" silently
    break video generation, and the purge sweep only covers that prefix.

    Dedup is `(lesson_id, original_filename, size_bytes)` — a match is skipped
    and the existing row is left untouched (its stored object may already be
    referenced by a signed URL a student holds, and its title/description may
    have been edited by hand).
    """
    filename = file.filename or ""
    try:
        existing = await list_materials(db, lesson_id)
        declared = file.size
        if declared is not None and any(
            m.original_filename == filename and m.size_bytes == declared for m in existing
        ):
            log.info("material_autoregister_duplicate", lesson_id=str(lesson_id), filename=filename)
            return None

        await file.seek(0)
        material = await add_material(
            db,
            lesson_id=lesson_id,
            uploaded_by=uploaded_by,
            file=file,
            title=None,
            description=None,
        )
        log.info("material_autoregistered", lesson_id=str(lesson_id), filename=filename)
        return material
    except Exception as exc:
        # Widest possible net on purpose — this path is best-effort by contract.
        log.warning(
            "material_autoregister_failed",
            lesson_id=str(lesson_id),
            filename=filename,
            error=str(exc),
        )
        return None
    finally:
        await file.seek(0)


# `material:<uuid>` inside a markdown link/image target. Matched case-insensitively
# on the uuid; the scheme itself is lower-case by construction (the editor writes it).
_MATERIAL_REF = re.compile(
    r"material:([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
    re.IGNORECASE,
)


def referenced_material_ids(markdown: str) -> set[UUID]:
    return {UUID(m) for m in _MATERIAL_REF.findall(markdown or "")}


async def save_text_body(db: AsyncSession, *, lesson: Lesson, text_content: str) -> list[UUID]:
    """Write a text lesson's markdown body and reclaim orphaned inline materials.

    Sole write path for `Lesson.text_content` (see schemas/lesson.LessonTextUpdate).
    An inline material no longer referenced anywhere in the new body is deleted
    storage-object-first, then row — the order `delete_material` uses, so a crash
    between the two leaves a reclaimable orphan file, never a row pointing at
    bytes that are gone. Returns the ids swept, for the caller to log/report.
    """
    referenced = referenced_material_ids(text_content)
    orphans = [
        m for m in await list_materials(db, lesson.id) if m.is_inline and m.id not in referenced
    ]

    lesson.text_content = text_content
    for material in orphans:
        storage_service.delete_file(material.file_path)
        await db.delete(material)
    await db.commit()
    await db.refresh(lesson)
    return [m.id for m in orphans]


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


# ── Course-level tree ────────────────────────────────────────────────────────


async def get_course_knowledge(
    db: AsyncSession, *, course: Course, viewer_id: str, is_owner: bool
) -> CourseKnowledgeTreeRead:
    """The whole course's knowledge base as module → lesson → (materials, notes).

    Replaces N calls to GET /lessons/{id}/knowledge. For a student the tree is
    pruned by `visibility_service` — the rule is never re-derived here. Note
    bodies are deliberately omitted (see CourseKnowledgeNoteRead).
    """
    modules = (
        await db.scalars(
            select(Module)
            .where(Module.course_id == course.id)
            .options(selectinload(Module.lessons))
            .order_by(Module.order, Module.created_at)
        )
    ).all()

    lesson_ids = [
        lesson.id
        for module in modules
        for lesson in module.lessons
        if is_owner or visibility_service.lesson_visible_to_student(module, lesson)
    ]

    materials: dict[UUID, list[LessonMaterial]] = {lid: [] for lid in lesson_ids}
    notes: dict[UUID, list[LessonNote]] = {lid: [] for lid in lesson_ids}
    if lesson_ids:
        for material in await db.scalars(
            select(LessonMaterial)
            .where(LessonMaterial.lesson_id.in_(lesson_ids))
            .order_by(LessonMaterial.created_at)
        ):
            materials[material.lesson_id].append(material)
        for note in await db.scalars(
            select(LessonNote)
            .where(LessonNote.lesson_id.in_(lesson_ids))
            .order_by(LessonNote.order, LessonNote.created_at)
        ):
            notes[note.lesson_id].append(note)

    tree: list[CourseKnowledgeModuleRead] = []
    for module in modules:
        if not is_owner and not visibility_service.module_visible_to_student(module):
            continue
        lessons = [
            CourseKnowledgeLessonRead(
                id=lesson.id,
                title=lesson.title,
                order=lesson.order,
                content_type=lesson.content_type.value,
                materials=[serialize_material(m, viewer_id) for m in materials[lesson.id]],
                notes=[CourseKnowledgeNoteRead.model_validate(n) for n in notes[lesson.id]],
            )
            for lesson in sorted(module.lessons, key=lambda x: (x.order, x.created_at))
            if lesson.id in materials
        ]
        tree.append(
            CourseKnowledgeModuleRead(
                id=module.id, title=module.title, order=module.order, lessons=lessons
            )
        )

    return CourseKnowledgeTreeRead(
        course_id=course.id,
        course_title=course.title,
        can_edit=is_owner,
        modules=tree,
    )
