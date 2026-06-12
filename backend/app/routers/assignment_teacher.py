"""Teacher-side assignment endpoints: CRUD + publish, submission review,
grade & return (one action), private thread, feedback files.

Plain `require_teacher` + ownership (get_owned_lesson / service loaders) — these
endpoints trigger no LLM/TTS/vision, so they are NOT in AI_GATED_ENDPOINTS and
need no verified-email gate, exactly like lesson/quiz authoring CRUD.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_owned_lesson, require_teacher
from app.limiter import limiter
from app.models.assignment import Assignment, AssignmentStatus, AttachmentKind
from app.models.lesson import Lesson
from app.models.user import User
from app.schemas.assignment import (
    AssignmentCreate,
    AssignmentTeacherListResponse,
    AssignmentTeacherRead,
    AssignmentUpdate,
    AttachmentRead,
    GradeRequest,
    MessageCreate,
    MessageRead,
    SubmissionListResponse,
    SubmissionSummaryTeacher,
    SubmissionTeacherRead,
)
from app.services import assignment_service

router = APIRouter(prefix="/api/v1", tags=["assignment-teacher"])


def _read(assignment: Assignment, counts: tuple[int, int]) -> AssignmentTeacherRead:
    read = AssignmentTeacherRead.model_validate(assignment)
    read.submission_count, read.pending_count = counts
    return read


# ── Assignment CRUD + publish ────────────────────────────────────────────────


@router.post(
    "/lessons/{lesson_id}/assignments",
    response_model=AssignmentTeacherRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_assignment(
    lesson_id: UUID,
    data: AssignmentCreate,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> AssignmentTeacherRead:
    assignment = await assignment_service.create_assignment(db, lesson.id, data)
    return _read(assignment, (0, 0))


@router.get(
    "/lessons/{lesson_id}/assignments",
    response_model=AssignmentTeacherListResponse,
)
async def list_assignments(
    lesson_id: UUID,
    lesson: Lesson = Depends(get_owned_lesson),
    db: AsyncSession = Depends(get_db),
) -> AssignmentTeacherListResponse:
    assignments = await assignment_service.list_assignments(db, lesson.id)
    counts = await assignment_service.submission_counts(db, [a.id for a in assignments])
    items = [_read(a, counts.get(a.id, (0, 0))) for a in assignments]
    return AssignmentTeacherListResponse(items=items, total=len(items))


@router.get("/assignments/{assignment_id}", response_model=AssignmentTeacherRead)
async def get_assignment(
    assignment_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> AssignmentTeacherRead:
    assignment = await assignment_service.get_owned_assignment(db, assignment_id, user.id)
    counts = await assignment_service.submission_counts(db, [assignment.id])
    return _read(assignment, counts.get(assignment.id, (0, 0)))


@router.patch("/assignments/{assignment_id}", response_model=AssignmentTeacherRead)
async def update_assignment(
    assignment_id: UUID,
    data: AssignmentUpdate,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> AssignmentTeacherRead:
    assignment = await assignment_service.get_owned_assignment(db, assignment_id, user.id)
    updates = data.model_dump(exclude_unset=True)
    assignment = await assignment_service.update_assignment(db, assignment, updates)
    counts = await assignment_service.submission_counts(db, [assignment.id])
    return _read(assignment, counts.get(assignment.id, (0, 0)))


@router.delete(
    "/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_assignment(
    assignment_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> Response:
    assignment = await assignment_service.get_owned_assignment(db, assignment_id, user.id)
    await assignment_service.delete_assignment(db, assignment)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/assignments/{assignment_id}/publish", response_model=AssignmentTeacherRead)
async def publish_assignment(
    assignment_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> AssignmentTeacherRead:
    assignment = await assignment_service.get_owned_assignment(db, assignment_id, user.id)
    assignment = await assignment_service.set_status(db, assignment, AssignmentStatus.published)
    counts = await assignment_service.submission_counts(db, [assignment.id])
    return _read(assignment, counts.get(assignment.id, (0, 0)))


@router.post("/assignments/{assignment_id}/unpublish", response_model=AssignmentTeacherRead)
async def unpublish_assignment(
    assignment_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> AssignmentTeacherRead:
    assignment = await assignment_service.get_owned_assignment(db, assignment_id, user.id)
    assignment = await assignment_service.set_status(db, assignment, AssignmentStatus.draft)
    counts = await assignment_service.submission_counts(db, [assignment.id])
    return _read(assignment, counts.get(assignment.id, (0, 0)))


# ── Submission review + grading ──────────────────────────────────────────────


@router.get(
    "/assignments/{assignment_id}/submissions",
    response_model=SubmissionListResponse,
)
async def list_submissions(
    assignment_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> SubmissionListResponse:
    assignment = await assignment_service.get_owned_assignment(db, assignment_id, user.id)
    submissions, attach_counts = await assignment_service.list_submissions(db, assignment.id)
    items = [
        SubmissionSummaryTeacher(
            id=s.id,
            student_id=s.enrollment.student.id,
            student_name=s.enrollment.student.full_name,
            student_email=s.enrollment.student.email,
            status=s.status,
            submitted_at=s.submitted_at,
            points_awarded=float(s.points_awarded) if s.points_awarded is not None else None,
            score=float(s.score) if s.score is not None else None,
            attachment_count=attach_counts.get(s.id, 0),
        )
        for s in submissions
    ]
    return SubmissionListResponse(items=items, total=len(items))


@router.get("/submissions/{submission_id}", response_model=SubmissionTeacherRead)
async def get_submission(
    submission_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> SubmissionTeacherRead:
    submission = await assignment_service.get_owned_submission(db, submission_id, user.id)
    return assignment_service.serialize_submission_teacher(submission, str(user.id))


@router.post("/submissions/{submission_id}/grade", response_model=SubmissionTeacherRead)
async def grade_submission(
    submission_id: UUID,
    data: GradeRequest,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> SubmissionTeacherRead:
    submission = await assignment_service.get_owned_submission(db, submission_id, user.id)
    assignment = await db.get(Assignment, submission.assignment_id)
    submission = await assignment_service.grade_submission(
        db, submission, assignment, data.points_awarded, data.feedback, user.id
    )
    return assignment_service.serialize_submission_teacher(submission, str(user.id))


@router.post("/submissions/{submission_id}/reopen", response_model=SubmissionTeacherRead)
async def reopen_submission(
    submission_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> SubmissionTeacherRead:
    submission = await assignment_service.get_owned_submission(db, submission_id, user.id)
    submission = await assignment_service.reopen_submission(db, submission)
    return assignment_service.serialize_submission_teacher(submission, str(user.id))


# ── Private thread + feedback files ──────────────────────────────────────────


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
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> MessageRead:
    await assignment_service.get_owned_submission(db, submission_id, user.id)
    message = await assignment_service.add_message(db, submission_id, user.id, data.body)
    return MessageRead.model_validate(message)


@router.post(
    "/submissions/{submission_id}/feedback-files",
    response_model=AttachmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_feedback_file(
    submission_id: UUID,
    file: UploadFile,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> AttachmentRead:
    submission = await assignment_service.get_owned_submission(db, submission_id, user.id)
    assignment = await db.get(Assignment, submission.assignment_id)
    attachment = await assignment_service.add_attachment(
        db, submission, assignment, file, AttachmentKind.feedback
    )
    return assignment_service.serialize_attachment(attachment, str(user.id))


@router.delete(
    "/submissions/{submission_id}/feedback-files/{attachment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_feedback_file(
    submission_id: UUID,
    attachment_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> Response:
    submission = await assignment_service.get_owned_submission(db, submission_id, user.id)
    # Teacher may only remove their own feedback files, not the student's work.
    target = next((a for a in submission.attachments if a.id == attachment_id), None)
    if target is None or target.kind != AttachmentKind.feedback:
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    await assignment_service.remove_attachment(db, submission, attachment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
