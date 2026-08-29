"""Account lifecycle end to end: delete → restore, delete → release → re-register,
and the purge that anonymizes instead of deleting."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, sessionmaker

from app.constants import ANONYMIZED_EMAIL_DOMAIN, PROFILE_DELETED_USER_NAME
from app.models.course import Course
from app.models.lesson import LessonStatus
from app.models.user import User, UserRole
from app.services import account_service
from app.services.auth_service import hash_password
from tests.factories import make_course, make_lesson, make_module

pytestmark = pytest.mark.integration

PASSWORD = "password123"


async def _make_account(db: AsyncSession, *, role: UserRole = UserRole.teacher) -> User:
    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password=hash_password(PASSWORD),
        full_name="Иван Петров",
        role=role,
        email_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _login(client: AsyncClient, user: User) -> dict[str, str]:
    resp = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {
        "access_token": resp.cookies["access_token"],
        "csrf_token": resp.cookies["csrf_token"],
    }


async def _reload(db: AsyncSession, user_id: uuid.UUID) -> User | None:
    db.expire_all()
    return await db.scalar(
        select(User).where(User.id == user_id).execution_options(include_deleted=True)
    )


# ── Deletion ─────────────────────────────────────────────────────────────────


async def test_delete_requires_correct_password(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_account(db_session)
    cookies = await _login(client, user)

    resp = await client.post(
        "/api/v1/users/me/delete", json={"password": "wrong-one"}, cookies=cookies
    )
    assert resp.status_code == 400

    assert (await _reload(db_session, user.id)).deleted_at is None


async def test_delete_soft_deletes_and_keeps_email_occupied(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    user = await _make_account(db_session)
    email, user_id = user.email, user.id
    cookies = await _login(client, user)

    resp = await client.post(
        "/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies
    )
    assert resp.status_code == 204

    row = await _reload(db_session, user_id)
    assert row.deleted_at is not None
    assert row.is_active is False
    # The address is NOT anonymized yet — restore and the 409 on register both
    # depend on the row still holding it.
    assert row.email == email
    assert row.full_name == "Иван Петров"

    # The restore link went out.
    assert mock_send_email.called
    kwargs = mock_send_email.call_args.kwargs
    assert kwargs["template_name"] == "account_deleted.html"
    assert kwargs["to"] == email
    assert "restore_url" in kwargs["context"]


async def test_delete_revokes_the_session(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    user = await _make_account(db_session)
    cookies = await _login(client, user)

    await client.post("/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies)

    assert (await client.get("/api/v1/auth/me", cookies=cookies)).status_code == 401


async def test_delete_is_idempotent(db_session: AsyncSession) -> None:
    """A second delete on an already-deleted row is a no-op, not an error, and
    must not move the deadline. Unreachable through the UI (the first call kills
    the cookie), so it is asserted at the service."""
    from app.services.auth_service import soft_delete_user

    user = await _make_account(db_session)
    soft_delete_user(user)
    await db_session.commit()
    first_deleted_at = user.deleted_at

    # Passing service=None proves the early return happens before any session
    # or Redis work — a real second call would have blown up here otherwise.
    await account_service.delete_own_account(
        db_session, None, user=user, password=PASSWORD, access_payload={}
    )

    assert (await _reload(db_session, user.id)).deleted_at == first_deleted_at


async def test_delete_blocked_while_a_lesson_is_generating(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    user = await _make_account(db_session)
    course = await make_course(db_session, owner=user)
    module = await make_module(db_session, course)
    await make_lesson(db_session, module, status=LessonStatus.processing)
    await db_session.commit()
    cookies = await _login(client, user)

    resp = await client.post(
        "/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "lessons_in_progress"
    assert (await _reload(db_session, user.id)).deleted_at is None


# ── Login / register during the window ───────────────────────────────────────


async def test_login_of_deleted_account_returns_403_with_code(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    user = await _make_account(db_session)
    cookies = await _login(client, user)
    await client.post("/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies)

    resp = await client.post("/api/v1/auth/login", json={"email": user.email, "password": PASSWORD})

    assert resp.status_code == 403
    detail = resp.json()["detail"]
    assert detail["code"] == "account_pending_deletion"
    assert detail["restore_until"]


async def test_wrong_password_on_deleted_account_stays_401(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    """Password is checked FIRST, so the pending-deletion answer never widens
    account enumeration: a guesser sees the same 401 as for any address."""
    user = await _make_account(db_session)
    cookies = await _login(client, user)
    await client.post("/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies)

    deleted = await client.post(
        "/api/v1/auth/login", json={"email": user.email, "password": "not-the-password"}
    )
    unknown = await client.post(
        "/api/v1/auth/login", json={"email": "nobody@example.com", "password": "whatever"}
    )

    assert deleted.status_code == unknown.status_code == 401
    assert deleted.json() == unknown.json()


async def test_register_with_occupied_email_returns_409_code(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    user = await _make_account(db_session)
    cookies = await _login(client, user)
    await client.post("/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies)

    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": user.email,
            "password": "brand-new-pass",
            "role": "teacher",
            "accepted_privacy": True,
            "accepted_terms": True,
        },
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "account_pending_deletion"


# ── Restore ──────────────────────────────────────────────────────────────────


async def test_delete_then_restore_by_credentials_then_login(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    user = await _make_account(db_session)
    user_id = user.id
    cookies = await _login(client, user)
    await client.post("/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies)

    resp = await client.post(
        "/api/v1/auth/restore-account", json={"email": user.email, "password": PASSWORD}
    )
    assert resp.status_code == 200

    row = await _reload(db_session, user_id)
    assert row.deleted_at is None
    assert row.is_active is True
    assert (
        await client.post("/api/v1/auth/login", json={"email": row.email, "password": PASSWORD})
    ).status_code == 200


async def test_restore_by_token_from_the_email(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    user = await _make_account(db_session)
    user_id = user.id
    cookies = await _login(client, user)
    await client.post("/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies)

    restore_url = mock_send_email.call_args.kwargs["context"]["restore_url"]
    token = restore_url.split("token=", 1)[1]

    assert (
        await client.post("/api/v1/auth/restore-account", json={"token": token})
    ).status_code == 200
    assert (await _reload(db_session, user_id)).deleted_at is None


async def test_restore_after_the_window_is_one_opaque_400(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    user = await _make_account(db_session)
    cookies = await _login(client, user)
    await client.post("/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies)

    # Age the row past the restore window.
    row = await _reload(db_session, user.id)
    row.deleted_at = datetime.now(timezone.utc) - timedelta(days=31)
    await db_session.commit()

    expired = await client.post(
        "/api/v1/auth/restore-account", json={"email": row.email, "password": PASSWORD}
    )
    garbage = await client.post("/api/v1/auth/restore-account", json={"token": "nonsense"})

    assert expired.status_code == garbage.status_code == 400
    assert expired.json() == garbage.json() == {"detail": "invalid_or_expired"}


async def test_restore_of_a_live_account_rejected(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    user = await _make_account(db_session)
    resp = await client.post(
        "/api/v1/auth/restore-account", json={"email": user.email, "password": PASSWORD}
    )
    assert resp.status_code == 400


# ── Email release ────────────────────────────────────────────────────────────


async def test_release_email_is_always_204(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    """Same answer for a real pending account and for an address we have never
    seen — the endpoint must not be an existence oracle."""
    unknown = await client.post("/api/v1/auth/release-email", json={"email": "nobody@example.com"})
    assert unknown.status_code == 204
    assert not mock_send_email.called

    user = await _make_account(db_session)
    cookies = await _login(client, user)
    await client.post("/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies)
    mock_send_email.reset_mock()

    known = await client.post("/api/v1/auth/release-email", json={"email": user.email})
    assert known.status_code == 204
    assert mock_send_email.call_args.kwargs["template_name"] == "email_release.html"


async def test_release_then_reregister_creates_a_new_account(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    user = await _make_account(db_session)
    email, old_id = user.email, user.id
    cookies = await _login(client, user)
    await client.post("/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies)

    mock_send_email.reset_mock()
    await client.post("/api/v1/auth/release-email", json={"email": email})
    release_url = mock_send_email.call_args.kwargs["context"]["release_url"]
    token = release_url.split("token=", 1)[1]

    assert (
        await client.post("/api/v1/auth/confirm-release", json={"token": token})
    ).status_code == 204

    # The old row survives, anonymized, and no longer holds the address.
    old = await _reload(db_session, old_id)
    assert old is not None
    assert old.email == f"deleted+{old_id}@{ANONYMIZED_EMAIL_DOMAIN}"
    assert old.full_name == PROFILE_DELETED_USER_NAME

    # The address is free: registering with it makes a genuinely new account.
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": email,
            "password": "a-brand-new-pass",
            "role": "teacher",
            "accepted_privacy": True,
            "accepted_terms": True,
        },
    )
    assert resp.status_code == 201
    assert resp.json()["id"] != str(old_id)


async def test_release_token_is_single_use(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    user = await _make_account(db_session)
    cookies = await _login(client, user)
    await client.post("/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies)
    mock_send_email.reset_mock()
    await client.post("/api/v1/auth/release-email", json={"email": user.email})
    token = mock_send_email.call_args.kwargs["context"]["release_url"].split("token=", 1)[1]

    assert (
        await client.post("/api/v1/auth/confirm-release", json={"token": token})
    ).status_code == 204
    assert (
        await client.post("/api/v1/auth/confirm-release", json={"token": token})
    ).status_code == 400


async def test_release_after_restore_does_not_anonymize(
    client: AsyncClient, db_session: AsyncSession, mock_send_email
) -> None:
    """Parallel release and restore on one account: the link predates the
    restore, so honouring it would anonymize a live account."""
    user = await _make_account(db_session)
    email, user_id = user.email, user.id
    cookies = await _login(client, user)
    await client.post("/api/v1/users/me/delete", json={"password": PASSWORD}, cookies=cookies)

    mock_send_email.reset_mock()
    await client.post("/api/v1/auth/release-email", json={"email": email})
    token = mock_send_email.call_args.kwargs["context"]["release_url"].split("token=", 1)[1]

    # Owner restores before clicking the release link.
    await client.post("/api/v1/auth/restore-account", json={"email": email, "password": PASSWORD})

    resp = await client.post("/api/v1/auth/confirm-release", json={"token": token})

    assert resp.status_code == 400
    row = await _reload(db_session, user_id)
    assert row.email == email
    assert row.deleted_at is None


# ── Purge (sync, mirrors the Celery worker) ──────────────────────────────────


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
        engine.dispose()


def _stale(days: int = 31) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def test_purge_anonymizes_a_teacher_with_enrolled_students(sync_session: Session) -> None:
    """Direct continuation of DECISIONS §51: the cascade would take the
    students' grades and history with the teacher's row."""
    from app.models.enrollment import Enrollment
    from app.models.lesson import Module
    from app.tasks.purge_pipeline import purge_soft_deleted

    teacher = User(
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password=hash_password(PASSWORD),
        full_name="Иван Петров",
        bio="Био",
        avatar_external_url="https://lh3.googleusercontent.com/a/x",
        role=UserRole.teacher,
        deleted_at=_stale(),
        is_active=False,
    )
    student = User(
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password=hash_password(PASSWORD),
        role=UserRole.student,
    )
    sync_session.add_all([teacher, student])
    sync_session.flush()
    course = Course(title="Курс", owner_id=teacher.id, is_published=True)
    sync_session.add(course)
    sync_session.flush()
    sync_session.add(Module(title="М", order=0, course_id=course.id, is_published=True))
    sync_session.add(Enrollment(student_id=student.id, course_id=course.id))
    sync_session.commit()
    teacher_id, course_id = teacher.id, course.id

    purge_soft_deleted()

    sync_session.expire_all()
    row = sync_session.scalar(
        select(User).where(User.id == teacher_id).execution_options(include_deleted=True)
    )
    # Row kept, personal data gone.
    assert row is not None
    assert row.email == f"deleted+{teacher_id}@{ANONYMIZED_EMAIL_DOMAIN}"
    assert row.full_name == PROFILE_DELETED_USER_NAME
    assert row.bio is None
    assert row.avatar_external_url is None
    assert row.deleted_at is not None
    # The course and the student's enrollment are untouched.
    assert sync_session.get(Course, course_id) is not None
    assert (
        sync_session.scalar(select(Enrollment).where(Enrollment.course_id == course_id)) is not None
    )


def test_purge_anonymizes_a_student_with_enrollments(sync_session: Session) -> None:
    from app.models.enrollment import Enrollment
    from app.tasks.purge_pipeline import purge_soft_deleted

    teacher = User(
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password=hash_password(PASSWORD),
        role=UserRole.teacher,
    )
    student = User(
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password=hash_password(PASSWORD),
        full_name="Студент",
        role=UserRole.student,
        deleted_at=_stale(),
        is_active=False,
    )
    sync_session.add_all([teacher, student])
    sync_session.flush()
    course = Course(title="Курс", owner_id=teacher.id)
    sync_session.add(course)
    sync_session.flush()
    sync_session.add(Enrollment(student_id=student.id, course_id=course.id))
    sync_session.commit()
    student_id = student.id

    purge_soft_deleted()

    sync_session.expire_all()
    row = sync_session.scalar(
        select(User).where(User.id == student_id).execution_options(include_deleted=True)
    )
    # The gradebook keeps a row reading "Удалённый пользователь" rather than
    # losing the student's results entirely.
    assert row is not None
    assert row.full_name == PROFILE_DELETED_USER_NAME


def test_purge_physically_deletes_an_empty_account(sync_session: Session) -> None:
    from app.tasks.purge_pipeline import purge_soft_deleted

    orphan = User(
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password=hash_password(PASSWORD),
        role=UserRole.student,
        deleted_at=_stale(),
        is_active=False,
    )
    sync_session.add(orphan)
    sync_session.commit()
    orphan_id = orphan.id

    purge_soft_deleted()

    sync_session.expire_all()
    assert (
        sync_session.scalar(
            select(User).where(User.id == orphan_id).execution_options(include_deleted=True)
        )
        is None
    )


def test_purge_leaves_accounts_inside_the_window(sync_session: Session) -> None:
    from app.tasks.purge_pipeline import purge_soft_deleted

    recent = User(
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password=hash_password(PASSWORD),
        full_name="Ещё восстановим",
        role=UserRole.student,
        deleted_at=datetime.now(timezone.utc) - timedelta(days=2),
        is_active=False,
    )
    sync_session.add(recent)
    sync_session.commit()
    recent_id, email = recent.id, recent.email

    purge_soft_deleted()

    sync_session.expire_all()
    row = sync_session.scalar(
        select(User).where(User.id == recent_id).execution_options(include_deleted=True)
    )
    assert row is not None
    assert row.email == email, "still restorable, so identity must survive"
