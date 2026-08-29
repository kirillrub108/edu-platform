"""Soft delete / course archive — routes, global filter, and purge task.

Route tests use the SAVEPOINT-rolled async `client`/`db_session` fixtures.
Purge tests use a separate psycopg2 `sync_session` (mirroring the Celery worker)
because the task holds its own connection; that DB is truncated after each test.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from app.models.assignment import (
    Assignment,
    AssignmentAttachment,
    AssignmentSubmission,
    AttachmentKind,
    SubmissionStatus,
)
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.lesson import ContentType, CreationMode, Lesson, LessonStatus, Module
from app.models.user import User, UserRole
from app.services.auth_service import hash_password
from tests.factories import make_course, make_enrollment

pytestmark = pytest.mark.integration


# ── Route tests (async) ──────────────────────────────────────────────────────


async def test_archive_returns_204_and_shows_in_grouped(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)

    resp = await client.delete(f"/api/v1/courses/{course.id}", cookies=teacher_token)
    assert resp.status_code == 204

    grouped = await client.get("/api/v1/courses/grouped", cookies=teacher_token)
    assert grouped.status_code == 200
    body = grouped.json()

    assert str(course.id) not in [c["id"] for c in body["published"]]
    archived = {c["id"]: c for c in body["archived"]}
    assert str(course.id) in archived
    assert archived[str(course.id)]["is_archived"] is True
    assert archived[str(course.id)]["days_until_purge"] == 30


async def test_double_archive_returns_409(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)

    r1 = await client.delete(f"/api/v1/courses/{course.id}", cookies=teacher_token)
    assert r1.status_code == 204
    r2 = await client.delete(f"/api/v1/courses/{course.id}", cookies=teacher_token)
    assert r2.status_code == 409


async def test_restore_moves_course_back_to_its_section(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=False)
    course.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await client.patch(f"/api/v1/courses/{course.id}/restore", cookies=teacher_token)
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_archived"] is False
    assert body["days_until_purge"] is None

    grouped = (await client.get("/api/v1/courses/grouped", cookies=teacher_token)).json()
    assert str(course.id) in [c["id"] for c in grouped["drafts"]]
    assert str(course.id) not in [c["id"] for c in grouped["archived"]]


async def test_restore_non_archived_returns_400(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    resp = await client.patch(f"/api/v1/courses/{course.id}/restore", cookies=teacher_token)
    assert resp.status_code == 400


async def test_archived_course_appears_in_my_courses_as_archived(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    await make_enrollment(db_session, student_user, course)

    resp = await client.get("/api/v1/students/my-courses", cookies=student_token)
    body = resp.json()
    assert str(course.id) in [c["id"] for c in body]
    assert next(c for c in body if c["id"] == str(course.id))["is_archived"] is False

    course.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await client.get("/api/v1/students/my-courses", cookies=student_token)
    assert resp.status_code == 200
    body = resp.json()
    # Archived course still visible — student retains access to their history.
    assert str(course.id) in [c["id"] for c in body]
    assert next(c for c in body if c["id"] == str(course.id))["is_archived"] is True


async def test_archived_course_direct_url_accessible_for_enrolled_student(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    await make_enrollment(db_session, student_user, course)
    course.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await client.get(f"/api/v1/students/courses/{course.id}", cookies=student_token)
    # Enrolled students can still open archived course content.
    assert resp.status_code == 200


async def test_enroll_into_an_archived_course_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_token: dict[str, str],
) -> None:
    """Archive closes the course to NEW enrollments even while it is still
    published — the two flags are independent levers. 404, not 400/403, so the
    API never reveals that an archived course exists."""
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    course.deleted_at = datetime.now(timezone.utc)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/students/enroll", json={"course_id": str(course.id)}, cookies=student_token
    )
    assert resp.status_code == 404


async def test_grouped_hides_the_purge_countdown_for_an_enrolled_archived_course(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    student_user: User,
) -> None:
    """An archived course with enrollments is retained forever, so the teacher
    must not be shown a deletion countdown for it."""
    empty = await make_course(db_session, owner=teacher_user)
    enrolled = await make_course(db_session, owner=teacher_user, is_published=True)
    await make_enrollment(db_session, student_user, enrolled)
    now = datetime.now(timezone.utc)
    empty.deleted_at = now
    enrolled.deleted_at = now
    await db_session.commit()

    resp = await client.get("/api/v1/courses/grouped", cookies=teacher_token)
    assert resp.status_code == 200
    archived = {c["id"]: c for c in resp.json()["archived"]}

    assert archived[str(empty.id)]["days_until_purge"] is not None
    assert archived[str(enrolled.id)]["enrollment_count"] == 1
    assert archived[str(enrolled.id)]["days_until_purge"] is None


async def test_soft_delete_user_blocks_auth_but_keeps_identity(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    """Soft delete marks and deactivates; it does NOT anonymize.

    Identity has to survive the restore window: the owner restores by
    email+password, and a re-registration on that address must answer 409
    rather than silently creating a second account. Anonymization is the end of
    the lifecycle instead — account_service.anonymize_user_fields, applied by
    purge or by an early email release (DECISIONS §59).
    """
    from app.services.auth_service import soft_delete_user

    assert (await client.get("/api/v1/auth/me", cookies=teacher_token)).status_code == 200

    original_email = teacher_user.email
    original_name = teacher_user.full_name
    soft_delete_user(teacher_user)
    await db_session.commit()

    assert teacher_user.is_active is False
    assert teacher_user.deleted_at is not None
    assert teacher_user.email == original_email
    assert teacher_user.full_name == original_name

    # is_active=False + global filter ⇒ get_current_user 401s on the next request.
    resp = await client.get("/api/v1/auth/me", cookies=teacher_token)
    assert resp.status_code == 401


# ── Purge task tests (sync) ──────────────────────────────────────────────────


@pytest.fixture()
def sync_session(_alembic_upgraded: None) -> Iterator[Session]:
    """psycopg2 session mirroring the Celery worker; truncates all tables after."""
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    sess = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE "
                    "lesson_progress, enrollments, slide_texts, quiz_questions, "
                    "lesson_videos, lessons, modules, courses, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
            conn.commit()
        engine.dispose()


def _make_user(sync_session: Session) -> User:
    import uuid

    user = User(
        email=f"t-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("password123"),
        role=UserRole.teacher,
        is_active=True,
    )
    sync_session.add(user)
    sync_session.commit()
    return user


def test_purge_only_removes_records_older_than_threshold(sync_session: Session) -> None:
    from app.tasks.purge_pipeline import purge_soft_deleted

    user = _make_user(sync_session)
    now = datetime.now(timezone.utc)
    old = Course(title="old", owner_id=user.id, deleted_at=now - timedelta(days=40))
    recent = Course(title="recent", owner_id=user.id, deleted_at=now - timedelta(days=10))
    sync_session.add_all([old, recent])
    sync_session.commit()
    old_id, recent_id = old.id, recent.id

    result = purge_soft_deleted()
    assert result["courses"] >= 1

    sync_session.expire_all()
    remaining = (
        sync_session.execute(
            select(Course.id)
            .where(Course.owner_id == user.id)
            .execution_options(include_deleted=True)
        )
        .scalars()
        .all()
    )
    assert old_id not in remaining
    assert recent_id in remaining


def test_purge_never_removes_an_archived_course_with_enrollments(
    sync_session: Session,
) -> None:
    """Archiving is teacher-side and does not revoke access, so a course anybody
    is enrolled in is retained indefinitely — a hard delete would cascade away
    the student's own enrollment, progress, attempts and submissions. A course
    with zero enrollments still purges on the usual timing."""
    from app.tasks.purge_pipeline import purge_soft_deleted

    teacher = _make_user(sync_session)
    student = _make_user(sync_session)
    long_ago = datetime.now(timezone.utc) - timedelta(days=400)
    enrolled = Course(title="enrolled", owner_id=teacher.id, deleted_at=long_ago)
    empty = Course(title="empty", owner_id=teacher.id, deleted_at=long_ago)
    sync_session.add_all([enrolled, empty])
    sync_session.commit()
    sync_session.add(Enrollment(student_id=student.id, course_id=enrolled.id))
    sync_session.commit()
    enrolled_id, empty_id = enrolled.id, empty.id

    purge_soft_deleted()

    sync_session.expire_all()
    remaining = (
        sync_session.execute(
            select(Course.id)
            .where(Course.owner_id == teacher.id)
            .execution_options(include_deleted=True)
        )
        .scalars()
        .all()
    )
    assert enrolled_id in remaining
    assert empty_id not in remaining
    # The enrollment itself (and everything cascading off it) survives too.
    assert (
        sync_session.scalar(select(Enrollment.id).where(Enrollment.course_id == enrolled_id))
        is not None
    )

    # Idempotent: a second run keeps retaining it rather than catching up.
    purge_soft_deleted()
    sync_session.expire_all()
    assert (
        sync_session.scalar(
            select(Course.id)
            .where(Course.id == enrolled_id)
            .execution_options(include_deleted=True)
        )
        is not None
    )


def test_purge_removes_stored_files(sync_session: Session) -> None:
    """_remove_file удаляет файл через storage_service.delete_file() (абстракция
    local/s3), а не os.remove напрямую — проверяем результат, а не сам вызов."""
    from app.services.storage_service import storage_service
    from app.tasks import purge_pipeline

    user = _make_user(sync_session)

    rel = "covers/purge-test.png"
    full = storage_service.get_full_path(rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(b"x")

    course = Course(
        title="c",
        owner_id=user.id,
        cover_url=f"http://testserver/files/{rel}",
        deleted_at=datetime.now(timezone.utc) - timedelta(days=40),
    )
    sync_session.add(course)
    sync_session.commit()

    purge_pipeline.purge_soft_deleted()

    assert not os.path.exists(full)


def _make_graded_attachment(session: Session, *, graded_days_ago: int | None) -> dict[str, object]:
    """Build user→course→…→submission→attachment with a real file on disk.
    graded_days_ago=None leaves the submission ungraded (graded_at NULL)."""
    from app.services.storage_service import storage_service

    teacher = _make_user(session)
    student = _make_user(session)
    course = Course(title="c", description="d", owner_id=teacher.id)
    session.add(course)
    session.commit()
    module = Module(title="m", order=0, course_id=course.id)
    session.add(module)
    session.commit()
    lesson = Lesson(
        title="l",
        order=0,
        module_id=module.id,
        content_type=ContentType.video,
        creation_mode=CreationMode.presentation_and_text,
        status=LessonStatus.draft,
    )
    session.add(lesson)
    session.commit()
    assignment = Assignment(lesson_id=lesson.id, title="a", prompt="p")
    enrollment = Enrollment(student_id=student.id, course_id=course.id)
    session.add_all([assignment, enrollment])
    session.commit()
    graded_at = (
        None
        if graded_days_ago is None
        else datetime.now(timezone.utc) - timedelta(days=graded_days_ago)
    )
    submission = AssignmentSubmission(
        assignment_id=assignment.id,
        enrollment_id=enrollment.id,
        status=SubmissionStatus.graded,
        graded_at=graded_at,
    )
    session.add(submission)
    session.commit()

    rel = f"assignments/{submission.id}/file.bin"
    full = storage_service.get_full_path(rel)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "wb") as fh:
        fh.write(b"xyz")
    attachment = AssignmentAttachment(
        submission_id=submission.id,
        kind=AttachmentKind.submission,
        file_path=rel,
        original_filename="file.bin",
        size_bytes=3,
    )
    session.add(attachment)
    session.commit()
    return {"att_id": attachment.id, "full": full}


def test_purge_retains_recent_and_ungraded_attachments(sync_session: Session) -> None:
    from app.constants import ATTACHMENT_RETENTION_DAYS_AFTER_GRADED as ret
    from app.tasks.purge_pipeline import purge_soft_deleted

    old = _make_graded_attachment(sync_session, graded_days_ago=ret + 5)
    recent = _make_graded_attachment(sync_session, graded_days_ago=ret - 5)
    ungraded = _make_graded_attachment(sync_session, graded_days_ago=None)
    survivors = [recent, ungraded]

    try:
        result = purge_soft_deleted()
        assert result["expired_attachments"] >= 1

        sync_session.expire_all()
        remaining = (
            sync_session.execute(
                select(AssignmentAttachment.id).execution_options(include_deleted=True)
            )
            .scalars()
            .all()
        )
        assert old["att_id"] not in remaining
        assert recent["att_id"] in remaining
        assert ungraded["att_id"] in remaining

        # File of the expired one is gone; the others are untouched.
        assert not os.path.exists(old["full"])  # type: ignore[arg-type]
        assert os.path.exists(recent["full"])  # type: ignore[arg-type]
        assert os.path.exists(ungraded["full"])  # type: ignore[arg-type]

        # Idempotent: a second run removes nothing new and does not raise.
        assert purge_soft_deleted()["expired_attachments"] == 0
    finally:
        for s in survivors:
            full = s["full"]
            if isinstance(full, str) and os.path.exists(full):
                os.remove(full)
