"""Pydantic v2 schemas for the assignments subsystem.

Dual Teacher/Student split: students never see other students' submissions, and
a submission's score/feedback is withheld until the teacher releases it
(status == returned). File paths are stored relative and expanded to signed
download URLs in the routers via storage_service.get_url.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.constants import (
    ASSIGNMENT_ALLOWED_EXTENSIONS,
    ASSIGNMENT_DEFAULT_MAX_FILE_MB,
    ASSIGNMENT_DEFAULT_MAX_FILES,
    ASSIGNMENT_DEFAULT_MAX_POINTS,
    ASSIGNMENT_MAX_FILE_MB,
    ASSIGNMENT_MAX_FILES,
    ASSIGNMENT_MAX_MESSAGE_CHARS,
    ASSIGNMENT_MAX_PROMPT_CHARS,
    ASSIGNMENT_MAX_TEXT_CHARS,
)
from app.models.assignment import AssignmentStatus, AttachmentKind, SubmissionStatus
from app.models.user import UserRole


def _strip_before(v: object) -> object:
    return v.strip() if isinstance(v, str) else v


def _normalize_ext(value: list[str] | None) -> list[str] | None:
    """Lower-case, drop the dot, dedupe, and reject anything outside the global
    whitelist. Empty/None → None (service falls back to the global default)."""
    if value is None:
        return None
    seen: list[str] = []
    for raw in value:
        ext = raw.lower().lstrip(".").strip()
        if not ext:
            continue
        if ext not in ASSIGNMENT_ALLOWED_EXTENSIONS:
            raise ValueError(f"extension not allowed: {raw}")
        if ext not in seen:
            seen.append(ext)
    return seen or None


# ── Assignment (teacher authoring) ───────────────────────────────────────────


class AssignmentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    prompt: str = Field(min_length=1, max_length=ASSIGNMENT_MAX_PROMPT_CHARS)
    max_points: float = Field(default=ASSIGNMENT_DEFAULT_MAX_POINTS, gt=0, le=100000)
    due_at: datetime | None = None
    attachments_enabled: bool = True
    max_files: int = Field(default=ASSIGNMENT_DEFAULT_MAX_FILES, ge=1, le=ASSIGNMENT_MAX_FILES)
    allowed_ext: list[str] | None = None
    max_file_mb: int = Field(
        default=ASSIGNMENT_DEFAULT_MAX_FILE_MB, ge=1, le=ASSIGNMENT_MAX_FILE_MB
    )
    pass_threshold: float | None = Field(default=None, ge=0, le=1)

    _strip_title = field_validator("title", mode="before")(_strip_before)
    _check_ext = field_validator("allowed_ext")(_normalize_ext)


class AssignmentUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    prompt: str | None = Field(default=None, min_length=1, max_length=ASSIGNMENT_MAX_PROMPT_CHARS)
    max_points: float | None = Field(default=None, gt=0, le=100000)
    due_at: datetime | None = None
    attachments_enabled: bool | None = None
    max_files: int | None = Field(default=None, ge=1, le=ASSIGNMENT_MAX_FILES)
    allowed_ext: list[str] | None = None
    max_file_mb: int | None = Field(default=None, ge=1, le=ASSIGNMENT_MAX_FILE_MB)
    pass_threshold: float | None = Field(default=None, ge=0, le=1)

    _strip_title = field_validator("title", mode="before")(_strip_before)
    _check_ext = field_validator("allowed_ext")(_normalize_ext)


class AssignmentTeacherRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lesson_id: UUID
    title: str
    prompt: str
    max_points: float
    due_at: datetime | None
    status: AssignmentStatus
    attachments_enabled: bool
    max_files: int
    allowed_ext: list[str]
    max_file_mb: int
    pass_threshold: float | None
    created_at: datetime
    updated_at: datetime
    submission_count: int = 0
    pending_count: int = 0  # submitted, awaiting grading


class AssignmentTeacherListResponse(BaseModel):
    items: list[AssignmentTeacherRead]
    total: int


# ── Attachments + thread (shared) ────────────────────────────────────────────


class AttachmentRead(BaseModel):
    id: UUID
    kind: AttachmentKind
    original_filename: str
    content_type: str | None
    size_bytes: int
    created_at: datetime
    download_url: str


class MessageAuthor(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    full_name: str | None
    role: UserRole


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    body: str
    author: MessageAuthor
    created_at: datetime


class MessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=ASSIGNMENT_MAX_MESSAGE_CHARS)

    _strip_body = field_validator("body", mode="before")(_strip_before)


# ── Submissions ──────────────────────────────────────────────────────────────


class SubmissionDraftUpdate(BaseModel):
    text_content: str | None = Field(default=None, max_length=ASSIGNMENT_MAX_TEXT_CHARS)


class SubmissionStudentRead(BaseModel):
    """The student's own submission. score/points/feedback are populated only
    once the teacher releases the grade (status == returned)."""

    id: UUID
    assignment_id: UUID
    text_content: str | None
    status: SubmissionStatus
    submitted_at: datetime | None
    points_awarded: float | None
    score: float | None
    feedback: str | None
    graded_at: datetime | None
    attachments: list[AttachmentRead]
    messages: list[MessageRead]


class SubmissionTeacherRead(BaseModel):
    id: UUID
    assignment_id: UUID
    enrollment_id: UUID
    student_id: UUID
    student_name: str | None
    student_email: str
    text_content: str | None
    status: SubmissionStatus
    submitted_at: datetime | None
    points_awarded: float | None
    score: float | None
    feedback: str | None
    graded_at: datetime | None
    attachments: list[AttachmentRead]
    messages: list[MessageRead]


class SubmissionSummaryTeacher(BaseModel):
    id: UUID
    student_id: UUID
    student_name: str | None
    student_email: str
    status: SubmissionStatus
    submitted_at: datetime | None
    points_awarded: float | None
    score: float | None
    attachment_count: int


class SubmissionListResponse(BaseModel):
    items: list[SubmissionSummaryTeacher]
    total: int


# ── Assignment as seen by an enrolled student ───────────────────────────────


class AssignmentStudentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    lesson_id: UUID
    title: str
    prompt: str
    max_points: float
    due_at: datetime | None
    attachments_enabled: bool
    max_files: int
    allowed_ext: list[str]
    max_file_mb: int
    pass_threshold: float | None
    my_submission: SubmissionStudentRead | None = None


class AssignmentStudentListResponse(BaseModel):
    items: list[AssignmentStudentRead]
    total: int


# ── Grading ──────────────────────────────────────────────────────────────────


class GradeRequest(BaseModel):
    points_awarded: float = Field(ge=0)
    feedback: str | None = Field(default=None, max_length=ASSIGNMENT_MAX_TEXT_CHARS)
