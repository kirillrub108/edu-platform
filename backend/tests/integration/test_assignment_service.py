"""Service-level tests for assignment_service: grading/normalization,
completion, the UNIQUE double-submit guard, submit validation, grade hiding,
and gradebook integration. DB-backed → integration marker."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.assignment import AssignmentSubmission, SubmissionStatus
from app.models.enrollment import LessonProgress
from app.models.user import User
from app.services import assignment_service, gradebook_service
from tests.factories import (
    make_assignment,
    make_assignment_submission,
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
)

pytestmark = pytest.mark.integration


async def _scaffold(db, teacher: User, student: User, **assignment_kw):
    course = await make_course(db, teacher, is_published=True)
    module = await make_module(db, course)
    lesson = await make_lesson(db, module)
    enrollment = await make_enrollment(db, student, course)
    assignment = await make_assignment(db, lesson, published=True, **assignment_kw)
    return course, lesson, enrollment, assignment


async def test_grade_normalizes_score_and_marks_completion(
    db_session, teacher_user: User, student_user: User
) -> None:
    _, lesson, enrollment, assignment = await _scaffold(
        db_session, teacher_user, student_user, max_points=50, pass_threshold=Decimal("0.6")
    )
    submission = await make_assignment_submission(
        db_session, assignment, enrollment, status=SubmissionStatus.submitted
    )

    graded = await assignment_service.grade_submission(
        db_session, submission, assignment, 40, "well done", teacher_user.id
    )

    assert graded.status == SubmissionStatus.returned
    assert float(graded.score) == pytest.approx(0.8)  # 40 / 50
    assert float(graded.points_awarded) == 40
    assert graded.graded_by == teacher_user.id

    progress = await db_session.scalar(
        select(LessonProgress).where(
            LessonProgress.enrollment_id == enrollment.id,
            LessonProgress.lesson_id == lesson.id,
        )
    )
    assert progress is not None
    assert progress.is_completed is True
    assert progress.completed_at is not None
    # Completion must NOT touch the quiz score column.
    assert progress.quiz_score is None


async def test_grade_below_threshold_does_not_complete(
    db_session, teacher_user: User, student_user: User
) -> None:
    _, lesson, enrollment, assignment = await _scaffold(
        db_session, teacher_user, student_user, max_points=50, pass_threshold=Decimal("0.9")
    )
    submission = await make_assignment_submission(
        db_session, assignment, enrollment, status=SubmissionStatus.submitted
    )

    await assignment_service.grade_submission(
        db_session, submission, assignment, 40, None, teacher_user.id
    )

    progress = await db_session.scalar(
        select(LessonProgress).where(
            LessonProgress.enrollment_id == enrollment.id,
            LessonProgress.lesson_id == lesson.id,
        )
    )
    assert progress is None or progress.is_completed is False


async def test_grade_points_out_of_range_raises_422(
    db_session, teacher_user: User, student_user: User
) -> None:
    _, _, enrollment, assignment = await _scaffold(
        db_session, teacher_user, student_user, max_points=50
    )
    submission = await make_assignment_submission(
        db_session, assignment, enrollment, status=SubmissionStatus.submitted
    )
    with pytest.raises(HTTPException) as exc:
        await assignment_service.grade_submission(
            db_session, submission, assignment, 60, None, teacher_user.id
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "points_out_of_range"


async def test_grade_draft_submission_raises_409(
    db_session, teacher_user: User, student_user: User
) -> None:
    _, _, enrollment, assignment = await _scaffold(
        db_session, teacher_user, student_user
    )
    submission = await make_assignment_submission(
        db_session, assignment, enrollment, status=SubmissionStatus.draft
    )
    with pytest.raises(HTTPException) as exc:
        await assignment_service.grade_submission(
            db_session, submission, assignment, 10, None, teacher_user.id
        )
    assert exc.value.status_code == 409


async def test_get_or_create_submission_is_idempotent(
    db_session, teacher_user: User, student_user: User
) -> None:
    _, _, enrollment, assignment = await _scaffold(
        db_session, teacher_user, student_user
    )
    first = await assignment_service.get_or_create_submission(
        db_session, assignment.id, enrollment.id
    )
    second = await assignment_service.get_or_create_submission(
        db_session, assignment.id, enrollment.id
    )
    assert first.id == second.id
    total = await db_session.scalar(
        select(func.count(AssignmentSubmission.id)).where(
            AssignmentSubmission.assignment_id == assignment.id
        )
    )
    assert total == 1


async def test_submit_requires_text_or_files(
    db_session, teacher_user: User, student_user: User
) -> None:
    _, _, enrollment, assignment = await _scaffold(
        db_session, teacher_user, student_user
    )
    submission = await assignment_service.get_or_create_submission(
        db_session, assignment.id, enrollment.id
    )
    with pytest.raises(HTTPException) as exc:
        await assignment_service.submit(db_session, submission, None)
    assert exc.value.status_code == 422
    assert exc.value.detail["code"] == "empty_submission"


async def test_submit_locked_after_returned(
    db_session, teacher_user: User, student_user: User
) -> None:
    _, _, enrollment, assignment = await _scaffold(
        db_session, teacher_user, student_user
    )
    submission = await make_assignment_submission(
        db_session, assignment, enrollment, status=SubmissionStatus.returned
    )
    with pytest.raises(HTTPException) as exc:
        await assignment_service.submit(db_session, submission, "late edit")
    assert exc.value.status_code == 409


async def test_student_serializer_hides_grade_until_returned(
    db_session, teacher_user: User, student_user: User
) -> None:
    _, _, enrollment, assignment = await _scaffold(
        db_session, teacher_user, student_user
    )
    await make_assignment_submission(
        db_session,
        assignment,
        enrollment,
        status=SubmissionStatus.graded,
        score=Decimal("0.9"),
        points_awarded=Decimal("90"),
        feedback="hidden",
    )
    loaded = await assignment_service.get_existing_submission(
        db_session, assignment.id, enrollment.id
    )
    hidden = assignment_service.serialize_submission_student(loaded, str(student_user.id))
    assert hidden.score is None
    assert hidden.feedback is None

    loaded.status = SubmissionStatus.returned
    await db_session.commit()
    loaded = await assignment_service.get_existing_submission(
        db_session, assignment.id, enrollment.id
    )
    shown = assignment_service.serialize_submission_student(loaded, str(student_user.id))
    assert shown.score == pytest.approx(0.9)
    assert shown.feedback == "hidden"


async def test_gradebook_includes_assignment_axis(
    db_session, teacher_user: User, student_user: User
) -> None:
    course, _, enrollment, assignment = await _scaffold(
        db_session, teacher_user, student_user, max_points=20
    )
    submission = await make_assignment_submission(
        db_session, assignment, enrollment, status=SubmissionStatus.submitted
    )
    await assignment_service.grade_submission(
        db_session, submission, assignment, 15, None, teacher_user.id
    )

    book = await gradebook_service.get_gradebook(course.id, course.title, db_session)
    assert len(book.assignments) == 1
    assert book.assignments[0].assignment_id == assignment.id
    assert book.assignments[0].max_points == pytest.approx(20)

    row = next(r for r in book.students if r.student_id == student_user.id)
    assert len(row.assignments) == 1
    cell = row.assignments[0]
    assert cell.status == "returned"
    assert cell.points_awarded == pytest.approx(15)
    assert cell.score == pytest.approx(0.75)
