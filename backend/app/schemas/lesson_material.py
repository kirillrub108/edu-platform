"""Lesson knowledge base: supplementary files (materials) + markdown notes."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants import (
    LESSON_MATERIAL_MAX_DESCRIPTION_CHARS,
    LESSON_MATERIAL_MAX_FILES,
    LESSON_MATERIAL_MAX_TOTAL_SIZE_MB,
    LESSON_NOTE_MAX_CONTENT_CHARS,
    LESSON_NOTE_MAX_TITLE_CHARS,
)


def _strip_before(v: object) -> object:
    """Pre-validator: strip incoming strings so `min_length=1` rejects
    whitespace-only input with the standard (JSON-serializable) error."""
    return v.strip() if isinstance(v, str) else v


def _strip_optional(v: object) -> object:
    """Same, but an all-whitespace value collapses to None (optional fields)."""
    if isinstance(v, str):
        stripped = v.strip()
        return stripped or None
    return v


# ── Materials ────────────────────────────────────────────────────────────────


class MaterialUpdate(BaseModel):
    """Metadata-only PATCH — the stored file itself is immutable (re-upload to
    replace it), which keeps storage cleanup a pure delete path."""

    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=LESSON_MATERIAL_MAX_DESCRIPTION_CHARS)

    _strip_title = field_validator("title", mode="before")(_strip_before)
    _strip_description = field_validator("description", mode="before")(_strip_optional)


class MaterialRead(BaseModel):
    id: UUID
    lesson_id: UUID
    title: str
    description: str | None
    original_filename: str
    content_type: str | None
    size_bytes: int
    uploaded_by: UUID | None
    created_at: datetime
    updated_at: datetime
    download_url: str


# ── Notes ────────────────────────────────────────────────────────────────────


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=LESSON_NOTE_MAX_TITLE_CHARS)
    content: str = Field(min_length=1, max_length=LESSON_NOTE_MAX_CONTENT_CHARS)

    _strip_title = field_validator("title", mode="before")(_strip_before)
    _strip_content = field_validator("content", mode="before")(_strip_before)


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=LESSON_NOTE_MAX_TITLE_CHARS)
    content: str | None = Field(
        default=None, min_length=1, max_length=LESSON_NOTE_MAX_CONTENT_CHARS
    )

    _strip_title = field_validator("title", mode="before")(_strip_before)
    _strip_content = field_validator("content", mode="before")(_strip_before)


class NotesReorder(BaseModel):
    """Full ordering of the lesson's notes — every id must belong to the lesson
    and the list must cover all of them, so `order` stays dense and total."""

    note_ids: list[UUID] = Field(min_length=1)


class NoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lesson_id: UUID
    title: str
    content: str
    order: int
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime


# ── Aggregate tab payload ────────────────────────────────────────────────────


class KnowledgeLimits(BaseModel):
    """Surfaced so the client can label the upload control without hard-coding
    the server's caps."""

    max_files: int = LESSON_MATERIAL_MAX_FILES
    max_total_mb: int = LESSON_MATERIAL_MAX_TOTAL_SIZE_MB
    allowed_ext: list[str]
    note_max_chars: int = LESSON_NOTE_MAX_CONTENT_CHARS


class KnowledgeBaseRead(BaseModel):
    materials: list[MaterialRead]
    notes: list[NoteRead]
    can_edit: bool
    limits: KnowledgeLimits
