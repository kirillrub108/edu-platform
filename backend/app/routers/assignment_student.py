"""Student-side assignment endpoints: see published assignments of enrolled
courses, draft/submit text + files, view status/grade/feedback, and the private
thread with the teacher.

Access is enrollment-scoped. The lesson-listing route reuses require_lesson_access;
per-assignment routes use the service's published+enrollment resolver, which 404s
draft assignments (no existence leak) and 403s non-enrolled students.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import require_lesson_access, require_student
from app.limiter import limiter
from app.models.assignment import AttachmentKind
from app.models.enrollment import Enrollment
from app.models.lesson import Lesson
from app.models.user import User
from app.schemas.assignment import (
    AssignmentStudentListResponse,
    AssignmentStudentRead,
    AttachmentRead,
    MessageCreate,
    MessageRead,
    SubmissionDraftUpdate,
    SubmissionStudentRead,
)
from app.services import assignment_service

router = APIRouter(prefix="/api/v1/students", tags=["assignment-student"])


def _read_pair(pair, viewer_id: str) -> AssignmentStudentRead:
    assignment, submission = pair
    read = AssignmentStudentRead.model_validate(assignment)
    if submission is not None:
        read.my_submission = assignment_service.serialize_submission_student(
            submission, viewer_id
        )
    return read


# ── Listing + detail ─────────────────────────────────────────────────────────


@router.get(
    "/lessons/{lesson_id}/assignments",
    response_model=AssignmentStudentListResponse,
)
async def list_assignments(
    lesson_id: UUID,
    access: tuple[User, Lesson, bool] = Depends(require_lesson_access),
    db: AsyncSession = Depends(get_db),
) -> AssignmentStudentListResponse:
    user, lesson, is_owner = access
    enrollment_id: UUID | None = None
    if not is_owner:
        enrollment_id = await db.scalar(
            select(Enrollment.id).where(
                Enrollment.student_id == user.id,
                Enrollment.course_id == lesson.module.course_id,
            )
        )
    pairs = await assignment_service.list_published_for_student(db, lesson_id, enrollment_id)
    items = [_read_pair(p, str(user.id)) for p in pairs]
    return AssignmentStudentListResponse(items=items, total=len(items))


@router.get("/assignments/{assignment_id}", response_model=AssignmentStudentRead)
async def get_assignment(
    assignment_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> AssignmentStudentRead:
    assignment, enrollment = await assignment_service.get_published_assignment_for_student(
        db, assignment_id, user.id
    )
    submission = await assignment_service.get_existing_submission(
        db, assignment.id, enrollment.id
    )
    read = AssignmentStudentRead.model_validate(assignment)
    if submission is not None:
        read.my_submission = assignment_service.serialize_submission_student(
            submission, str(user.id)
        )
    return read


# ── Draft / submit ───────────────────────────────────────────────────────────


@router.put(
    "/assignments/{assignment_id}/submission",
    response_model=SubmissionStudentRead,
)
async def save_draft(
    assignment_id: UUID,
    data: SubmissionDraftUpdate,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> SubmissionStudentRead:
    assignment, enrollment = await assignment_service.get_published_assignment_for_student(
        db, assignment_id, user.id
    )
    submission = await assignment_service.get_or_create_submission(
        db, assignment.id, enrollment.id
    )
    submission = await assignment_service.save_draft(db, submission, data.text_content)
    return assignment_service.serialize_submission_student(submission, str(user.id))


@router.post(
    "/assignments/{assignment_id}/submission/submit",
    response_model=SubmissionStudentRead,
)
async def submit(
    assignment_id: UUID,
    data: SubmissionDraftUpdate,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> SubmissionStudentRead:
    assignment, enrollment = await assignment_service.get_published_assignment_for_student(
        db, assignment_id, user.id
    )
    submission = await assignment_service.get_or_create_submission(
        db, assignment.id, enrollment.id
    )
    submission = await assignment_service.submit(db, submission, data.text_content)
    return assignment_service.serialize_submission_student(submission, str(user.id))


# ── Attachments ──────────────────────────────────────────────────────────────


@router.post(
    "/assignments/{assignment_id}/submission/files",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    assignment_id: UUID,
    file: UploadFile,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> AttachmentRead:
    assignment, enrollment = await assignment_service.get_published_assignment_for_student(
        db, assignment_id, user.id
    )
    submission = await assignment_service.get_or_create_submission(
        db, assignment.id, enrollment.id
    )
    attachment = await assignment_service.add_attachment(
        db, submission, assignment, file, AttachmentKind.submission
    )
    return assignment_service.serialize_attachment(attachment, str(user.id))


@router.delete(
    "/submissions/{submission_id}/files/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_file(
    submission_id: UUID,
    attachment_id: UUID,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> Response:
    submission = await assignment_service.get_own_submission(db, submission_id, user.id)
    target = next((a for a in submission.attachments if a.id == attachment_id), None)
    if target is None or target.kind != AttachmentKind.submission:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    await assignment_service.remove_attachment(db, submission, attachment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Private thread ───────────────────────────────────────────────────────────


@router.post(
    "/submissions/{submission_id}/messages",
    response_model=MessageRead,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def post_message(
    request: Request,
    submission_id: UUID,
    data: MessageCreate,
    user: User = Depends(require_student),
    db: AsyncSession = Depends(get_db),
) -> MessageRead:
    await assignment_service.get_own_submission(db, submission_id, user.id)
    message = await assignment_service.add_message(db, submission_id, user.id, data.body)
    return MessageRead.model_validate(message)
