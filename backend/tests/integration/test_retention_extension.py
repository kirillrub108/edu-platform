"""Paid extension of submission-attachment retention.

Two halves, matching the two runtimes that touch it:
  * the purge task (psycopg2 `sync_session`, mirroring the Celery worker) must
    honour an extended deadline;
  * the teacher endpoint (async `client`) must reserve → charge and stack.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from app.constants import (
    ATTACHMENT_RETENTION_DAYS_AFTER_GRADED,
    RETENTION_EXTENSION_DAYS,
)
from app.models.assignment import (
    Assignment,
    AssignmentAttachment,
    AssignmentSubmission,
    AttachmentKind,
    SubmissionStatus,
)
from app.models.course import Course
from app.models.credit import CreditAccount, CreditOperation, CreditPlan, CreditTransaction
from app.models.enrollment import Enrollment
from app.models.lesson import ContentType, CreationMode, Lesson, LessonStatus, Module
from app.models.user import User, UserRole
from app.services.auth_service import hash_password
from app.services.billing_service import estimate_retention_extension
from tests.factories import (
    make_assignment,
    make_assignment_submission,
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
)

pytestmark = pytest.mark.integration

# Attachment sizes used by the fixtures below. Both are tiny, so the formula
# prices them at the cheapest tier — the point of naming them is that the
# assertions follow the formula rather than a hardcoded credit count.
_SYNC_ATTACHMENT_BYTES = 3
_ENDPOINT_ATTACHMENT_BYTES = 10


# ── Purge side (sync, mirrors the Celery worker) ─────────────────────────────


@pytest.fixture()
def sync_session(_alembic_upgraded: None) -> Iterator[Session]:
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
                    "TRUNCATE TABLE assignment_attachments, assignment_submissions, "
                    "assignments, enrollments, lessons, modules, courses, users "
                    "RESTART IDENTITY CASCADE"
                )
            )
            conn.commit()
        engine.dispose()


def _make_user(session: Session) -> User:
    user = User(
        email=f"t-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("password123"),
        role=UserRole.teacher,
        is_active=True,
    )
    session.add(user)
    session.commit()
    return user


def _make_expired_submission_with_file(
    session: Session, *, retain_until: datetime | None
) -> dict[str, Any]:
    """A submission graded long past the free window, so only `retain_until`
    can keep its attachment alive."""
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

    submission = AssignmentSubmission(
        assignment_id=assignment.id,
        enrollment_id=enrollment.id,
        status=SubmissionStatus.graded,
        graded_at=datetime.now(timezone.utc)
        - timedelta(days=ATTACHMENT_RETENTION_DAYS_AFTER_GRADED + 5),
        attachments_retain_until=retain_until,
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
    return {"att_id": attachment.id, "full": full, "submission_id": submission.id}


def test_purge_spares_an_extended_submission_past_the_base_window(
    sync_session: Session,
) -> None:
    """Both rows are long past graded_at + base window. Only the extended one
    survives — proving the sweep reads the effective deadline, not the constant."""
    from app.tasks.purge_pipeline import purge_soft_deleted

    future = datetime.now(timezone.utc) + timedelta(days=RETENTION_EXTENSION_DAYS)
    extended = _make_expired_submission_with_file(sync_session, retain_until=future)
    plain = _make_expired_submission_with_file(sync_session, retain_until=None)

    try:
        purge_soft_deleted()

        sync_session.expire_all()
        remaining = (
            sync_session.execute(
                select(AssignmentAttachment.id).execution_options(include_deleted=True)
            )
            .scalars()
            .all()
        )
        assert extended["att_id"] in remaining, "paid extension was ignored by the purge"
        assert plain["att_id"] not in remaining

        assert os.path.exists(extended["full"])
        assert not os.path.exists(plain["full"])
    finally:
        if os.path.exists(extended["full"]):
            os.remove(extended["full"])


def test_purge_removes_an_extension_that_has_itself_expired(sync_session: Session) -> None:
    """An extension only buys time — once its own deadline passes the files go."""
    from app.tasks.purge_pipeline import purge_soft_deleted

    lapsed = datetime.now(timezone.utc) - timedelta(days=1)
    row = _make_expired_submission_with_file(sync_session, retain_until=lapsed)

    purge_soft_deleted()

    sync_session.expire_all()
    remaining = (
        sync_session.execute(
            select(AssignmentAttachment.id).execution_options(include_deleted=True)
        )
        .scalars()
        .all()
    )
    assert row["att_id"] not in remaining
    assert not os.path.exists(row["full"])


# ── Pre-deletion reminder (sync beat job) ────────────────────────────────────


def test_reminder_is_sent_once_and_only_inside_the_window(
    sync_session: Session, mock_send_email: Any
) -> None:
    """One mail per retention window: the submission inside the window gets it,
    the one still far from its deadline does not, and a second run of the beat
    job mails nobody again."""
    from app.tasks.purge_pipeline import notify_expiring_attachments

    now = datetime.now(timezone.utc)
    due = _make_expired_submission_with_file(sync_session, retain_until=now + timedelta(days=1))
    far = _make_expired_submission_with_file(sync_session, retain_until=now + timedelta(days=365))

    try:
        result = notify_expiring_attachments()
        assert result["sent"] == 1

        recipients = [c.kwargs["template_name"] for c in mock_send_email.call_args_list]
        assert recipients == ["attachments_expiring.html"]

        sync_session.expire_all()
        due_row = sync_session.get(AssignmentSubmission, due["submission_id"])
        far_row = sync_session.get(AssignmentSubmission, far["submission_id"])
        assert due_row.retention_reminder_sent_at is not None
        assert far_row.retention_reminder_sent_at is None

        # One-shot: the daily beat must not re-mail the same window.
        mock_send_email.reset_mock()
        assert notify_expiring_attachments()["sent"] == 0
        assert mock_send_email.call_count == 0
    finally:
        for row in (due, far):
            if os.path.exists(row["full"]):
                os.remove(row["full"])


def test_reminder_reports_what_expires_and_how_to_extend(
    sync_session: Session, mock_send_email: Any
) -> None:
    """The mail must name the file count, the date and the extension price."""
    from app.tasks.purge_pipeline import notify_expiring_attachments

    deadline = datetime.now(timezone.utc) + timedelta(days=1)
    row = _make_expired_submission_with_file(sync_session, retain_until=deadline)

    try:
        notify_expiring_attachments()

        ctx = mock_send_email.call_args.kwargs["context"]
        assert ctx["attachment_count"] == 1
        assert ctx["expires_at"] == deadline.strftime("%d.%m.%Y")
        assert ctx["extension_days"] == RETENTION_EXTENSION_DAYS
        assert ctx["extension_credits"] == estimate_retention_extension(_SYNC_ATTACHMENT_BYTES)
        assert ctx["lesson_url"].startswith("http")
    finally:
        if os.path.exists(row["full"]):
            os.remove(row["full"])


def test_reminder_skips_submissions_whose_files_are_already_gone(
    sync_session: Session, mock_send_email: Any
) -> None:
    """No attachments left → nothing to warn about, but the row is flagged so the
    beat job stops rescanning it every night."""
    from app.tasks.purge_pipeline import notify_expiring_attachments

    row = _make_expired_submission_with_file(
        sync_session, retain_until=datetime.now(timezone.utc) + timedelta(days=1)
    )
    attachment = sync_session.get(AssignmentAttachment, row["att_id"])
    sync_session.delete(attachment)
    sync_session.commit()
    os.remove(row["full"])

    assert notify_expiring_attachments()["sent"] == 0
    assert mock_send_email.call_count == 0

    sync_session.expire_all()
    submission = sync_session.get(AssignmentSubmission, row["submission_id"])
    assert submission.retention_reminder_sent_at is not None


def test_extension_reopens_the_reminder_for_the_new_window(sync_session: Session) -> None:
    """A paid extension clears the one-shot flag, so the teacher is warned again
    before the NEW deadline instead of being silently cut off."""
    from app.tasks.purge_pipeline import notify_expiring_attachments

    row = _make_expired_submission_with_file(
        sync_session, retain_until=datetime.now(timezone.utc) + timedelta(days=1)
    )
    try:
        notify_expiring_attachments()
        sync_session.expire_all()
        submission = sync_session.get(AssignmentSubmission, row["submission_id"])
        assert submission.retention_reminder_sent_at is not None

        # What extend_retention does to the row (its own transaction is async).
        submission.attachments_retain_until = datetime.now(timezone.utc) + timedelta(
            days=RETENTION_EXTENSION_DAYS
        )
        submission.retention_reminder_sent_at = None
        sync_session.commit()

        # Far from the new deadline → quiet until the window comes round again.
        assert notify_expiring_attachments()["sent"] == 0
    finally:
        if os.path.exists(row["full"]):
            os.remove(row["full"])


# ── Endpoint side (async) ────────────────────────────────────────────────────


async def _graded_submission(
    db: AsyncSession,
    teacher: User,
    student: User,
    *,
    size_bytes: int = _ENDPOINT_ATTACHMENT_BYTES,
) -> AssignmentSubmission:
    course = await make_course(db, owner=teacher, is_published=True)
    module = await make_module(db, course)
    lesson = await make_lesson(db, module)
    assignment = await make_assignment(db, lesson, published=True)
    enrollment = await make_enrollment(db, student=student, course=course)
    submission = await make_assignment_submission(
        db,
        assignment,
        enrollment,
        status=SubmissionStatus.graded,
        graded_at=datetime.now(timezone.utc),
    )
    db.add(
        AssignmentAttachment(
            submission_id=submission.id,
            kind=AttachmentKind.submission,
            file_path=f"assignments/{submission.id}/essay.pdf",
            original_filename="essay.pdf",
            size_bytes=size_bytes,
        )
    )
    await db.commit()
    return submission


async def _fund(db: AsyncSession, user: User, credits: int) -> CreditAccount:
    account = await db.scalar(select(CreditAccount).where(CreditAccount.owner_id == user.id))
    if account is None:
        account = CreditAccount(owner_id=user.id, plan=CreditPlan.free, balance=0, reserved=0)
        db.add(account)
    account.balance = credits
    account.reserved = 0
    await db.commit()
    return account


async def test_extend_charges_credits_and_moves_the_deadline(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    cost = estimate_retention_extension(_ENDPOINT_ATTACHMENT_BYTES)
    submission = await _graded_submission(db_session, teacher_user, student_user)
    account = await _fund(db_session, teacher_user, cost * 3)

    before = await client.get(f"/api/v1/submissions/{submission.id}", cookies=teacher_token)
    assert before.status_code == 200
    base_expiry = datetime.fromisoformat(before.json()["attachments_expire_at"])

    resp = await client.post(
        f"/api/v1/submissions/{submission.id}/extend-retention", cookies=teacher_token
    )
    assert resp.status_code == 200, resp.text
    new_expiry = datetime.fromisoformat(resp.json()["attachments_expire_at"])
    assert new_expiry == base_expiry + timedelta(days=RETENTION_EXTENSION_DAYS)

    await db_session.refresh(account)
    assert account.balance == cost * 3 - cost
    assert account.reserved == 0, "the hold must be fully settled, not left dangling"

    ops = (
        await db_session.scalars(
            select(CreditTransaction.operation).where(CreditTransaction.account_id == account.id)
        )
    ).all()
    assert CreditOperation.RESERVE in ops
    assert CreditOperation.RETENTION_EXTEND in ops


async def test_repeat_extension_stacks_and_charges_again(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    """Documented semantics: extensions add up rather than being idempotent, and
    every call reports the resulting effective deadline."""
    cost = estimate_retention_extension(_ENDPOINT_ATTACHMENT_BYTES)
    submission = await _graded_submission(db_session, teacher_user, student_user)
    account = await _fund(db_session, teacher_user, cost * 4)

    first = await client.post(
        f"/api/v1/submissions/{submission.id}/extend-retention", cookies=teacher_token
    )
    second = await client.post(
        f"/api/v1/submissions/{submission.id}/extend-retention", cookies=teacher_token
    )
    assert first.status_code == 200
    assert second.status_code == 200

    d1 = datetime.fromisoformat(first.json()["attachments_expire_at"])
    d2 = datetime.fromisoformat(second.json()["attachments_expire_at"])
    assert d2 == d1 + timedelta(days=RETENTION_EXTENSION_DAYS)

    await db_session.refresh(account)
    assert account.balance == cost * 4 - 2 * cost
    assert account.reserved == 0


async def test_extend_without_credits_returns_402_and_changes_nothing(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    submission = await _graded_submission(db_session, teacher_user, student_user)
    await _fund(db_session, teacher_user, 0)

    resp = await client.post(
        f"/api/v1/submissions/{submission.id}/extend-retention", cookies=teacher_token
    )
    assert resp.status_code == 402
    assert resp.json()["detail"]["code"] == "insufficient_credits"

    await db_session.refresh(submission)
    assert submission.attachments_retain_until is None


async def test_extend_after_files_were_purged_returns_409_without_charging(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    """The purge already ran: there is nothing to keep, so refuse before
    reserving rather than sell the teacher an empty extension."""
    cost = estimate_retention_extension(_ENDPOINT_ATTACHMENT_BYTES)
    submission = await _graded_submission(db_session, teacher_user, student_user)
    account = await _fund(db_session, teacher_user, cost * 2)

    for att in (
        await db_session.scalars(
            select(AssignmentAttachment).where(AssignmentAttachment.submission_id == submission.id)
        )
    ).all():
        await db_session.delete(att)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/submissions/{submission.id}/extend-retention", cookies=teacher_token
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "attachments_already_removed"

    await db_session.refresh(account)
    assert account.balance == cost * 2
    assert account.reserved == 0


async def test_extend_is_scoped_to_the_owning_teacher(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    submission = await _graded_submission(db_session, teacher_user, student_user)

    resp = await client.post(
        f"/api/v1/submissions/{submission.id}/extend-retention", cookies=student_token
    )
    assert resp.status_code in (403, 404)


async def test_price_scales_with_attachment_size_end_to_end(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    """The headline behaviour change: a 1 GB submission costs materially more to
    keep than a 200 KB one, where the old flat weight charged both the same."""
    small = await _graded_submission(db_session, teacher_user, student_user, size_bytes=200 * 1024)
    large = await _graded_submission(
        db_session, teacher_user, student_user, size_bytes=1024 * 1024 * 1024
    )
    account = await _fund(db_session, teacher_user, 1000)

    small_quote = await client.get(f"/api/v1/submissions/{small.id}", cookies=teacher_token)
    large_quote = await client.get(f"/api/v1/submissions/{large.id}", cookies=teacher_token)
    small_price = small_quote.json()["retention_extension_credits"]
    large_price = large_quote.json()["retention_extension_credits"]
    assert large_price > small_price

    before = account.balance
    assert (
        await client.post(f"/api/v1/submissions/{small.id}/extend-retention", cookies=teacher_token)
    ).status_code == 200
    await db_session.refresh(account)
    charged_small = before - account.balance

    before = account.balance
    assert (
        await client.post(f"/api/v1/submissions/{large.id}/extend-retention", cookies=teacher_token)
    ).status_code == 200
    await db_session.refresh(account)
    charged_large = before - account.balance

    # The advertised preview and the actual charge agree, and size drives both.
    assert charged_small == small_price
    assert charged_large == large_price
    assert charged_large > charged_small


async def test_extra_files_raise_the_price_of_the_next_extension(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    """Pricing reads the CURRENT bytes, so files added after the first extension
    are billed on the next one instead of riding along free."""
    submission = await _graded_submission(db_session, teacher_user, student_user, size_bytes=1024)
    await _fund(db_session, teacher_user, 1000)

    first = await client.post(
        f"/api/v1/submissions/{submission.id}/extend-retention", cookies=teacher_token
    )
    assert first.status_code == 200
    cheap_price = first.json()["retention_extension_credits"]

    db_session.add(
        AssignmentAttachment(
            submission_id=submission.id,
            kind=AttachmentKind.feedback,
            file_path=f"assignments/{submission.id}/big.mp4",
            original_filename="big.mp4",
            size_bytes=600 * 1024 * 1024,
        )
    )
    await db_session.commit()

    second = await client.get(f"/api/v1/submissions/{submission.id}", cookies=teacher_token)
    assert second.json()["retention_extension_credits"] > cheap_price
