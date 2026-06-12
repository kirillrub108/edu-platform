"""Assignments: teacher authoring + grading and student submissions.

Synchronous (request/response) — no Celery, no LLM. Files are only stored, never
parsed server-side. The normalized 0..1 score on a submission is what the
gradebook reads (see gradebook_service); completion is an optional, best-attempt
flag on LessonProgress that never touches quiz_score.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import (
    ASSIGNMENT_ALLOWED_EXTENSIONS,
    ATTACHMENT_ALLOWED_TYPES,
    ATTACHMENT_CATEGORY_MAX_SIZE_MB,
    ATTACHMENT_EXTENSION_MIME,
    ATTACHMENT_MAX_FILES,
    ATTACHMENT_MAX_TOTAL_SIZE_MB,
)
from app.models.assignment import (
    Assignment,
    AssignmentAttachment,
    AssignmentMessage,
    AssignmentStatus,
    AssignmentSubmission,
    AttachmentKind,
    SubmissionStatus,
)
from app.models.course import Course
from app.models.enrollment import Enrollment, LessonProgress
from app.models.lesson import Lesson, Module
from app.schemas.assignment import (
    AssignmentCreate,
    AttachmentRead,
    MessageRead,
    SubmissionStudentRead,
    SubmissionTeacherRead,
)
from app.services.file_validation_service import validate_upload
from app.services.grading_service import aggregate_score
from app.services.storage_service import storage_service

_LOCKED_STATUSES = {SubmissionStatus.graded, SubmissionStatus.returned}


# ── Serialization (relative paths → signed download URLs) ────────────────────


def serialize_attachment(att: AssignmentAttachment, viewer_id: str) -> AttachmentRead:
    return AttachmentRead(
        id=att.id,
        kind=att.kind,
        original_filename=att.original_filename,
        content_type=att.content_type,
        size_bytes=att.size_bytes,
        created_at=att.created_at,
        download_url=storage_service.get_url(att.file_path, viewer_id),
    )


def _messages(submission: AssignmentSubmission) -> list[MessageRead]:
    return [MessageRead.model_validate(m) for m in submission.messages]


def serialize_submission_student(
    submission: AssignmentSubmission, viewer_id: str
) -> SubmissionStudentRead:
    released = submission.status == SubmissionStatus.returned
    return SubmissionStudentRead(
        id=submission.id,
        assignment_id=submission.assignment_id,
        text_content=submission.text_content,
        status=submission.status,
        submitted_at=submission.submitted_at,
        points_awarded=float(submission.points_awarded)
        if released and submission.points_awarded is not None
        else None,
        score=float(submission.score) if released and submission.score is not None else None,
        feedback=submission.feedback if released else None,
        graded_at=submission.graded_at if released else None,
        attachments=[serialize_attachment(a, viewer_id) for a in submission.attachments],
        messages=_messages(submission),
    )


def serialize_submission_teacher(
    submission: AssignmentSubmission, viewer_id: str
) -> SubmissionTeacherRead:
    student = submission.enrollment.student
    return SubmissionTeacherRead(
        id=submission.id,
        assignment_id=submission.assignment_id,
        enrollment_id=submission.enrollment_id,
        student_id=student.id,
        student_name=student.full_name,
        student_email=student.email,
        text_content=submission.text_content,
        status=submission.status,
        submitted_at=submission.submitted_at,
        points_awarded=float(submission.points_awarded)
        if submission.points_awarded is not None
        else None,
        score=float(submission.score) if submission.score is not None else None,
        feedback=submission.feedback,
        graded_at=submission.graded_at,
        attachments=[serialize_attachment(a, viewer_id) for a in submission.attachments],
        messages=_messages(submission),
    )


# ── Authorized loaders ───────────────────────────────────────────────────────


def _submission_options() -> list:
    return [
        selectinload(AssignmentSubmission.attachments),
        selectinload(AssignmentSubmission.messages),
        selectinload(AssignmentSubmission.enrollment).selectinload(Enrollment.student),
    ]


async def _load_with_options(
    db: AsyncSession, submission_id: UUID
) -> AssignmentSubmission | None:
    return await db.scalar(
        select(AssignmentSubmission)
        .where(AssignmentSubmission.id == submission_id)
        .options(*_submission_options())
        # populate_existing so a submission already in the identity map gets its
        # attachments/messages collections refreshed from the DB rather than
        # reused stale (matters whenever one session serves several operations).
        .execution_options(populate_existing=True)
    )


async def get_owned_assignment(
    db: AsyncSession, assignment_id: UUID, owner_id: UUID
) -> Assignment:
    assignment = await db.scalar(
        select(Assignment)
        .join(Lesson, Assignment.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .where(Assignment.id == assignment_id, Course.owner_id == owner_id)
    )
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    return assignment


async def get_owned_submission(
    db: AsyncSession, submission_id: UUID, owner_id: UUID
) -> AssignmentSubmission:
    submission = await db.scalar(
        select(AssignmentSubmission)
        .join(Assignment, AssignmentSubmission.assignment_id == Assignment.id)
        .join(Lesson, Assignment.lesson_id == Lesson.id)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .where(AssignmentSubmission.id == submission_id, Course.owner_id == owner_id)
        .options(*_submission_options())
        .execution_options(populate_existing=True)
    )
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    return submission


async def get_published_assignment_for_student(
    db: AsyncSession, assignment_id: UUID, student_id: UUID
) -> tuple[Assignment, Enrollment]:
    # The join carries the global soft-delete filter on Lesson, so an assignment
    # under a soft-deleted lesson resolves to nothing → 404.
    row = (
        await db.execute(
            select(Assignment, Module.course_id)
            .join(Lesson, Assignment.lesson_id == Lesson.id)
            .join(Module, Lesson.module_id == Module.id)
            .where(Assignment.id == assignment_id)
        )
    ).first()
    # A draft assignment must be invisible — 404, not 403, so existence doesn't leak.
    if row is None or row[0].status != AssignmentStatus.published:
        raise HTTPException(status_code=404, detail="Assignment not found")
    assignment, course_id = row
    enrollment = await db.scalar(
        select(Enrollment).where(
            Enrollment.student_id == student_id,
            Enrollment.course_id == course_id,
        )
    )
    if enrollment is None:
        raise HTTPException(status_code=403, detail="Not enrolled in this course")
    return assignment, enrollment


async def get_own_submission(
    db: AsyncSession, submission_id: UUID, student_id: UUID
) -> AssignmentSubmission:
    submission = await db.scalar(
        select(AssignmentSubmission)
        .join(Enrollment, AssignmentSubmission.enrollment_id == Enrollment.id)
        .where(
            AssignmentSubmission.id == submission_id,
            Enrollment.student_id == student_id,
        )
        .options(*_submission_options())
        .execution_options(populate_existing=True)
    )
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found")
    return submission


# ── Teacher: assignment CRUD + publish ───────────────────────────────────────


async def create_assignment(
    db: AsyncSession, lesson_id: UUID, data: AssignmentCreate
) -> Assignment:
    assignment = Assignment(
        lesson_id=lesson_id,
        title=data.title,
        prompt=data.prompt,
        max_points=Decimal(str(data.max_points)),
        due_at=data.due_at,
        attachments_enabled=data.attachments_enabled,
        allowed_ext=data.allowed_ext or list(ASSIGNMENT_ALLOWED_EXTENSIONS),
        pass_threshold=Decimal(str(data.pass_threshold))
        if data.pass_threshold is not None
        else None,
    )
    db.add(assignment)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def update_assignment(
    db: AsyncSession, assignment: Assignment, updates: dict
) -> Assignment:
    for key, value in updates.items():
        if key in ("max_points",) and value is not None:
            value = Decimal(str(value))
        elif key == "pass_threshold" and value is not None:
            value = Decimal(str(value))
        elif key == "allowed_ext":
            value = value or list(ASSIGNMENT_ALLOWED_EXTENSIONS)
        setattr(assignment, key, value)
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def set_status(
    db: AsyncSession, assignment: Assignment, status: AssignmentStatus
) -> Assignment:
    assignment.status = status
    await db.commit()
    await db.refresh(assignment)
    return assignment


async def delete_assignment(db: AsyncSession, assignment: Assignment) -> None:
    # Gather attachment paths before the row cascade removes them, then delete
    # the files so no orphans linger in storage.
    paths = await db.scalars(
        select(AssignmentAttachment.file_path)
        .join(
            AssignmentSubmission,
            AssignmentAttachment.submission_id == AssignmentSubmission.id,
        )
        .where(AssignmentSubmission.assignment_id == assignment.id)
    )
    for path in paths.all():
        storage_service.delete_file(path)
    await db.delete(assignment)
    await db.commit()


async def list_assignments(db: AsyncSession, lesson_id: UUID) -> list[Assignment]:
    rows = await db.scalars(
        select(Assignment)
        .where(Assignment.lesson_id == lesson_id)
        .order_by(Assignment.created_at)
    )
    return list(rows.all())


async def submission_counts(
    db: AsyncSession, assignment_ids: list[UUID]
) -> dict[UUID, tuple[int, int]]:
    """assignment_id -> (total submissions, submitted-and-awaiting-grading)."""
    if not assignment_ids:
        return {}
    rows = await db.execute(
        select(
            AssignmentSubmission.assignment_id,
            func.count(AssignmentSubmission.id),
            func.count(AssignmentSubmission.id).filter(
                AssignmentSubmission.status == SubmissionStatus.submitted
            ),
        )
        .where(AssignmentSubmission.assignment_id.in_(assignment_ids))
        .group_by(AssignmentSubmission.assignment_id)
    )
    return {aid: (total, pending) for aid, total, pending in rows.all()}


async def list_submissions(
    db: AsyncSession, assignment_id: UUID
) -> tuple[list[AssignmentSubmission], dict[UUID, int]]:
    """Submissions with student loaded + a {submission_id: attachment_count} map."""
    rows = await db.scalars(
        select(AssignmentSubmission)
        .where(AssignmentSubmission.assignment_id == assignment_id)
        .options(selectinload(AssignmentSubmission.enrollment).selectinload(Enrollment.student))
        .order_by(AssignmentSubmission.created_at)
    )
    submissions = list(rows.all())
    counts: dict[UUID, int] = {}
    ids = [s.id for s in submissions]
    if ids:
        count_rows = await db.execute(
            select(AssignmentAttachment.submission_id, func.count(AssignmentAttachment.id))
            .where(
                AssignmentAttachment.submission_id.in_(ids),
                AssignmentAttachment.kind == AttachmentKind.submission,
            )
            .group_by(AssignmentAttachment.submission_id)
        )
        counts = {sid: c for sid, c in count_rows.all()}
    return submissions, counts


# ── Teacher: grading ─────────────────────────────────────────────────────────


async def grade_submission(
    db: AsyncSession,
    submission: AssignmentSubmission,
    assignment: Assignment,
    points_awarded: float,
    feedback: str | None,
    grader_id: UUID,
) -> AssignmentSubmission:
    if submission.status == SubmissionStatus.draft:
        raise HTTPException(
            status_code=409, detail={"code": "submission_not_submitted"}
        )
    max_points = float(assignment.max_points)
    if points_awarded < 0 or points_awarded > max_points:
        raise HTTPException(
            status_code=422,
            detail={"code": "points_out_of_range", "max_points": max_points},
        )

    # Normalize to 0..1 via the same weighted aggregator the quiz grade uses
    # (single item, weight 1). `passed` drives optional lesson completion.
    threshold = assignment.pass_threshold if assignment.pass_threshold is not None else Decimal("0")
    agg = aggregate_score(
        [(Decimal("1"), Decimal(str(points_awarded)), Decimal(str(max_points)))],
        Decimal(threshold),
    )

    submission.points_awarded = Decimal(str(points_awarded))
    submission.score = agg.score
    submission.feedback = feedback
    submission.status = SubmissionStatus.returned  # grade & return in one action
    submission.graded_at = datetime.now(timezone.utc)
    submission.graded_by = grader_id

    if assignment.pass_threshold is not None and agg.passed:
        await _mark_completion(db, submission.enrollment_id, assignment.lesson_id)

    # No refresh: expire_on_commit=False keeps the loaded relationships intact
    # (serialization touches them), and eager_defaults already populated updated_at.
    await db.commit()
    return submission


async def reopen_submission(
    db: AsyncSession, submission: AssignmentSubmission
) -> AssignmentSubmission:
    """Unlock a graded/returned submission so the student can resubmit. The old
    grade stays on the row but is hidden from the student while status != returned."""
    submission.status = SubmissionStatus.submitted
    await db.commit()
    return submission


async def _mark_completion(db: AsyncSession, enrollment_id: UUID, lesson_id: UUID) -> None:
    progress = await db.scalar(
        select(LessonProgress).where(
            LessonProgress.enrollment_id == enrollment_id,
            LessonProgress.lesson_id == lesson_id,
        )
    )
    if progress is None:
        progress = LessonProgress(enrollment_id=enrollment_id, lesson_id=lesson_id)
        db.add(progress)
    # Best-attempt: only ever marks complete, never reverts, never touches quiz_score.
    if not progress.is_completed:
        progress.is_completed = True
        progress.completed_at = datetime.now(timezone.utc)


# ── Student: submission lifecycle ────────────────────────────────────────────


async def get_existing_submission(
    db: AsyncSession, assignment_id: UUID, enrollment_id: UUID
) -> AssignmentSubmission | None:
    return await db.scalar(
        select(AssignmentSubmission)
        .where(
            AssignmentSubmission.assignment_id == assignment_id,
            AssignmentSubmission.enrollment_id == enrollment_id,
        )
        .options(*_submission_options())
        .execution_options(populate_existing=True)
    )


async def get_or_create_submission(
    db: AsyncSession, assignment_id: UUID, enrollment_id: UUID
) -> AssignmentSubmission:
    submission = await db.scalar(
        select(AssignmentSubmission)
        .where(
            AssignmentSubmission.assignment_id == assignment_id,
            AssignmentSubmission.enrollment_id == enrollment_id,
        )
        .options(*_submission_options())
    )
    if submission is not None:
        return submission

    submission = AssignmentSubmission(
        assignment_id=assignment_id,
        enrollment_id=enrollment_id,
        status=SubmissionStatus.draft,
    )
    db.add(submission)
    try:
        await db.commit()
    except IntegrityError:
        # Lost the double-submit race against the UNIQUE constraint — re-select.
        await db.rollback()
        submission = await db.scalar(
            select(AssignmentSubmission)
            .where(
                AssignmentSubmission.assignment_id == assignment_id,
                AssignmentSubmission.enrollment_id == enrollment_id,
            )
            .options(*_submission_options())
        )
        if submission is None:
            raise
        return submission
    # Re-select so the (empty) relationship collections are eagerly loaded —
    # touching them lazily would crash the async session.
    loaded = await _load_with_options(db, submission.id)
    assert loaded is not None
    return loaded


def _ensure_editable(submission: AssignmentSubmission) -> None:
    if submission.status in _LOCKED_STATUSES:
        raise HTTPException(status_code=409, detail={"code": "submission_locked"})


async def save_draft(
    db: AsyncSession, submission: AssignmentSubmission, text_content: str | None
) -> AssignmentSubmission:
    _ensure_editable(submission)
    submission.text_content = text_content
    await db.commit()
    return submission


async def submit(
    db: AsyncSession,
    submission: AssignmentSubmission,
    text_content: str | None,
) -> AssignmentSubmission:
    _ensure_editable(submission)
    if text_content is not None:
        submission.text_content = text_content
    has_text = bool((submission.text_content or "").strip())
    has_files = any(
        a.kind == AttachmentKind.submission for a in submission.attachments
    )
    if not has_text and not has_files:
        raise HTTPException(status_code=422, detail={"code": "empty_submission"})
    submission.status = SubmissionStatus.submitted
    submission.submitted_at = datetime.now(timezone.utc)
    await db.commit()
    return submission


async def list_published_for_student(
    db: AsyncSession, lesson_id: UUID, enrollment_id: UUID | None
) -> list[tuple[Assignment, AssignmentSubmission | None]]:
    """Published assignments of a lesson, each paired with this student's
    submission (or None). enrollment_id None (e.g. teacher preview) → no submissions."""
    assignments = list(
        (
            await db.scalars(
                select(Assignment)
                .where(
                    Assignment.lesson_id == lesson_id,
                    Assignment.status == AssignmentStatus.published,
                )
                .order_by(Assignment.created_at)
            )
        ).all()
    )
    if not assignments or enrollment_id is None:
        return [(a, None) for a in assignments]
    aids = [a.id for a in assignments]
    subs = await db.scalars(
        select(AssignmentSubmission)
        .where(
            AssignmentSubmission.enrollment_id == enrollment_id,
            AssignmentSubmission.assignment_id.in_(aids),
        )
        .options(
            selectinload(AssignmentSubmission.attachments),
            selectinload(AssignmentSubmission.messages),
        )
    )
    by_aid = {s.assignment_id: s for s in subs.all()}
    return [(a, by_aid.get(a.id)) for a in assignments]


# ── Attachments ──────────────────────────────────────────────────────────────


def _mb(num_bytes: int) -> float:
    return round(num_bytes / (1024 * 1024), 1)


def _resolve_attachment_category(file: UploadFile) -> tuple[str, str]:
    """Return (category, ext) for an upload, by MIME with an extension fallback.

    The extension MUST be on the whitelist, even when the MIME type already
    resolves — this rejects a forged Content-Type riding on a disallowed
    extension (e.g. ".exe" sent as image/png).
    """
    ext = os.path.splitext(file.filename or "")[1].lower().lstrip(".")
    ext_mime = ATTACHMENT_EXTENSION_MIME.get(ext)
    if ext_mime is None:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "extension_not_allowed",
                "message": f"Тип файла «{file.filename or ext or 'неизвестно'}» не поддерживается.",
            },
        )
    mime = (file.content_type or "").split(";")[0].strip().lower()
    category = ATTACHMENT_ALLOWED_TYPES.get(mime) or ATTACHMENT_ALLOWED_TYPES[ext_mime]
    return category, ext


async def add_attachment(
    db: AsyncSession,
    submission: AssignmentSubmission,
    assignment: Assignment,
    file: UploadFile,
    kind: AttachmentKind,
) -> AssignmentAttachment:
    if not assignment.attachments_enabled:
        raise HTTPException(status_code=400, detail={"code": "attachments_disabled"})
    if kind == AttachmentKind.submission:
        _ensure_editable(submission)

    siblings = [a for a in submission.attachments if a.kind == kind]
    if len(siblings) >= ATTACHMENT_MAX_FILES:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "too_many_files",
                "max_files": ATTACHMENT_MAX_FILES,
                "message": f"Слишком много файлов: не более {ATTACHMENT_MAX_FILES} на одну сдачу.",
            },
        )

    category, ext = _resolve_attachment_category(file)

    size = file.size
    if size is None:
        data = await file.read()
        size = len(data)
        await file.seek(0)

    cat_limit_mb = ATTACHMENT_CATEGORY_MAX_SIZE_MB[category]
    if size > cat_limit_mb * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "file_too_large",
                "category": category,
                "max_file_mb": cat_limit_mb,
                "message": (
                    f"Файл «{file.filename}» — {_mb(size)} МБ, "
                    f"для категории «{category}» допускается до {cat_limit_mb} МБ."
                ),
            },
        )

    total = sum(a.size_bytes for a in siblings) + size
    if total > ATTACHMENT_MAX_TOTAL_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "submission_too_large",
                "max_total_mb": ATTACHMENT_MAX_TOTAL_SIZE_MB,
                "message": (
                    f"Суммарный объём сдачи {_mb(total)} МБ превышает лимит "
                    f"{ATTACHMENT_MAX_TOTAL_SIZE_MB} МБ."
                ),
            },
        )

    # Deep safety: magic-byte + zip-bomb/zip-slip checks (no XML parsing). Size is
    # governed by the per-category limit above, so SIZE_LIMITS is skipped here.
    await validate_upload(file, [f".{ext}"], enforce_size_limits=False)

    relative = await storage_service.save_upload(file, f"assignments/{submission.id}")
    attachment = AssignmentAttachment(
        submission_id=submission.id,
        kind=kind,
        file_path=relative,
        original_filename=file.filename or f"file.{ext}",
        content_type=file.content_type,
        size_bytes=size,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return attachment


async def remove_attachment(
    db: AsyncSession, submission: AssignmentSubmission, attachment_id: UUID
) -> None:
    attachment = next((a for a in submission.attachments if a.id == attachment_id), None)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")
    if attachment.kind == AttachmentKind.submission:
        _ensure_editable(submission)
    storage_service.delete_file(attachment.file_path)
    await db.delete(attachment)
    await db.commit()


# ── Private thread ───────────────────────────────────────────────────────────


async def add_message(
    db: AsyncSession, submission_id: UUID, author_id: UUID, body: str
) -> AssignmentMessage:
    message = AssignmentMessage(
        submission_id=submission_id, author_id=author_id, body=body
    )
    db.add(message)
    await db.commit()
    await db.refresh(message, attribute_names=["author"])
    return message
