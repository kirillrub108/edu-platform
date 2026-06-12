"""End-to-end assignment routes: teacher CRUD/publish/grade, student
draft/submit/files/thread, authorization boundaries, and gradebook reflection."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from tests.factories import (
    make_assignment,
    make_assignment_submission,
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
)

pytestmark = pytest.mark.integration


async def _scaffold(db: AsyncSession, teacher: User, student: User, *, enroll=True):
    course = await make_course(db, teacher, is_published=True)
    module = await make_module(db, course)
    lesson = await make_lesson(db, module)
    if enroll:
        await make_enrollment(db, student, course)
    return course, module, lesson


async def test_full_flow_create_publish_submit_grade_gradebook(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
    student_token: dict[str, str],
) -> None:
    course, _, lesson = await _scaffold(db_session, teacher_user, student_user)

    created = await client.post(
        f"/api/v1/lessons/{lesson.id}/assignments",
        json={
            "title": "Essay",
            "prompt": "Write 500 words",
            "max_points": 20,
            "pass_threshold": 0.5,
        },
        cookies=teacher_token,
    )
    assert created.status_code == 201, created.text
    assignment_id = created.json()["id"]
    assert created.json()["status"] == "draft"

    # Student can't see a draft assignment.
    hidden = await client.get(
        f"/api/v1/students/assignments/{assignment_id}", cookies=student_token
    )
    assert hidden.status_code == 404

    pub = await client.post(
        f"/api/v1/assignments/{assignment_id}/publish", cookies=teacher_token
    )
    assert pub.status_code == 200
    assert pub.json()["status"] == "published"

    # Student now sees it and submits.
    listing = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/assignments", cookies=student_token
    )
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    submit = await client.post(
        f"/api/v1/students/assignments/{assignment_id}/submission/submit",
        json={"text_content": "My essay answer"},
        cookies=student_token,
    )
    assert submit.status_code == 200, submit.text
    submission_id = submit.json()["id"]
    assert submit.json()["status"] == "submitted"
    # Grade not visible yet.
    assert submit.json()["score"] is None

    # Teacher sees the submission in the list and grades it.
    subs = await client.get(
        f"/api/v1/assignments/{assignment_id}/submissions", cookies=teacher_token
    )
    assert subs.json()["total"] == 1
    assert subs.json()["items"][0]["status"] == "submitted"

    grade = await client.post(
        f"/api/v1/submissions/{submission_id}/grade",
        json={"points_awarded": 16, "feedback": "Good work"},
        cookies=teacher_token,
    )
    assert grade.status_code == 200, grade.text
    assert grade.json()["status"] == "returned"
    assert grade.json()["points_awarded"] == 16

    # Student now sees the grade + feedback.
    mine = await client.get(
        f"/api/v1/students/assignments/{assignment_id}", cookies=student_token
    )
    assert mine.json()["my_submission"]["feedback"] == "Good work"
    assert mine.json()["my_submission"]["score"] == pytest.approx(0.8)

    # Gradebook surfaces the assignment axis.
    book = await client.get(
        f"/api/v1/courses/{course.id}/gradebook", cookies=teacher_token
    )
    assert book.status_code == 200
    body = book.json()
    assert len(body["assignments"]) == 1
    assert body["assignments"][0]["assignment_id"] == assignment_id
    cell = body["students"][0]["assignments"][0]
    assert cell["points_awarded"] == 16
    assert cell["score"] == pytest.approx(0.8)


async def test_points_out_of_range_returns_422(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    from sqlalchemy import select

    from app.models.enrollment import Enrollment

    _, _, lesson = await _scaffold(db_session, teacher_user, student_user)
    enrollment = await db_session.scalar(
        select(Enrollment).where(Enrollment.student_id == student_user.id)
    )
    assignment = await make_assignment(db_session, lesson, published=True, max_points=10)
    submission = await make_assignment_submission(db_session, assignment, enrollment)

    resp = await client.post(
        f"/api/v1/submissions/{submission.id}/grade",
        json={"points_awarded": 50},
        cookies=teacher_token,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "points_out_of_range"


async def test_submit_empty_returns_422(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await _scaffold(db_session, teacher_user, student_user)
    assignment = await make_assignment(db_session, lesson, published=True)

    resp = await client.post(
        f"/api/v1/students/assignments/{assignment.id}/submission/submit",
        json={"text_content": "   "},
        cookies=student_token,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "empty_submission"


async def test_resubmit_after_graded_409_then_reopen(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await _scaffold(db_session, teacher_user, student_user)
    assignment = await make_assignment(db_session, lesson, published=True, max_points=10)
    from sqlalchemy import select

    from app.models.enrollment import Enrollment

    enrollment = await db_session.scalar(
        select(Enrollment).where(Enrollment.student_id == student_user.id)
    )
    submission = await make_assignment_submission(db_session, assignment, enrollment)

    await client.post(
        f"/api/v1/submissions/{submission.id}/grade",
        json={"points_awarded": 8},
        cookies=teacher_token,
    )

    blocked = await client.post(
        f"/api/v1/students/assignments/{assignment.id}/submission/submit",
        json={"text_content": "let me redo"},
        cookies=student_token,
    )
    assert blocked.status_code == 409

    reopen = await client.post(
        f"/api/v1/submissions/{submission.id}/reopen", cookies=teacher_token
    )
    assert reopen.status_code == 200

    again = await client.post(
        f"/api/v1/students/assignments/{assignment.id}/submission/submit",
        json={"text_content": "redone"},
        cookies=student_token,
    )
    assert again.status_code == 200


async def test_non_enrolled_student_cannot_view_assignment(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await _scaffold(db_session, teacher_user, student_user, enroll=False)
    assignment = await make_assignment(db_session, lesson, published=True)

    resp = await client.get(
        f"/api/v1/students/assignments/{assignment.id}", cookies=student_token
    )
    assert resp.status_code == 403


async def test_other_student_cannot_touch_submission(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
) -> None:
    from app.models.user import UserRole
    from app.services.auth_service import create_access_token, hash_password

    _, course_module, lesson = await _scaffold(db_session, teacher_user, student_user)
    from sqlalchemy import select

    from app.models.enrollment import Enrollment

    enrollment = await db_session.scalar(
        select(Enrollment).where(Enrollment.student_id == student_user.id)
    )
    assignment = await make_assignment(db_session, lesson, published=True)
    submission = await make_assignment_submission(db_session, assignment, enrollment)

    other = User(
        email=f"other-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("x"),
        full_name="Other",
        role=UserRole.student,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    token, _, _ = create_access_token(other)
    other_token = {"access_token": token, "csrf_token": "test-csrf-fixed-value"}

    resp = await client.post(
        f"/api/v1/students/submissions/{submission.id}/messages",
        json={"body": "sneaky"},
        cookies=other_token,
    )
    assert resp.status_code == 404


async def test_other_teacher_cannot_grade(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
) -> None:
    from app.models.user import UserRole
    from app.services.auth_service import create_access_token, hash_password

    _, _, lesson = await _scaffold(db_session, teacher_user, student_user)
    from sqlalchemy import select

    from app.models.enrollment import Enrollment

    enrollment = await db_session.scalar(
        select(Enrollment).where(Enrollment.student_id == student_user.id)
    )
    assignment = await make_assignment(db_session, lesson, published=True, max_points=10)
    submission = await make_assignment_submission(db_session, assignment, enrollment)

    intruder = User(
        email=f"t2-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("x"),
        full_name="Teacher Two",
        role=UserRole.teacher,
        is_active=True,
        email_verified=True,
    )
    db_session.add(intruder)
    await db_session.commit()
    token, _, _ = create_access_token(intruder)
    intruder_token = {"access_token": token, "csrf_token": "test-csrf-fixed-value"}

    resp = await client.post(
        f"/api/v1/submissions/{submission.id}/grade",
        json={"points_awarded": 5},
        cookies=intruder_token,
    )
    assert resp.status_code == 404


async def test_file_upload_then_submit_with_file_only(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await _scaffold(db_session, teacher_user, student_user)
    assignment = await make_assignment(db_session, lesson, published=True)

    # Disallowed extension is rejected with a machine-readable code.
    bad = await client.post(
        f"/api/v1/students/assignments/{assignment.id}/submission/files",
        files={"file": ("malware.exe", b"MZ\x90\x00", "application/octet-stream")},
        cookies=student_token,
    )
    assert bad.status_code == 400
    assert bad.json()["detail"]["code"] == "extension_not_allowed"

    ok = await client.post(
        f"/api/v1/students/assignments/{assignment.id}/submission/files",
        files={"file": ("answer.txt", b"my essay answer", "text/plain")},
        cookies=student_token,
    )
    assert ok.status_code == 201, ok.text

    # Submit with no text but a file present succeeds.
    submit = await client.post(
        f"/api/v1/students/assignments/{assignment.id}/submission/submit",
        json={"text_content": None},
        cookies=student_token,
    )
    assert submit.status_code == 200, submit.text
    assert len(submit.json()["attachments"]) == 1
    assert submit.json()["attachments"][0]["download_url"]


async def test_private_thread_both_roles(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await _scaffold(db_session, teacher_user, student_user)
    from sqlalchemy import select

    from app.models.enrollment import Enrollment

    enrollment = await db_session.scalar(
        select(Enrollment).where(Enrollment.student_id == student_user.id)
    )
    assignment = await make_assignment(db_session, lesson, published=True)
    submission = await make_assignment_submission(db_session, assignment, enrollment)

    s_msg = await client.post(
        f"/api/v1/students/submissions/{submission.id}/messages",
        json={"body": "When is it due?"},
        cookies=student_token,
    )
    assert s_msg.status_code == 201
    assert s_msg.json()["author"]["role"] == "student"

    t_msg = await client.post(
        f"/api/v1/submissions/{submission.id}/messages",
        json={"body": "Friday"},
        cookies=teacher_token,
    )
    assert t_msg.status_code == 201
    assert t_msg.json()["author"]["role"] == "teacher"

    detail = await client.get(
        f"/api/v1/submissions/{submission.id}", cookies=teacher_token
    )
    assert len(detail.json()["messages"]) == 2
