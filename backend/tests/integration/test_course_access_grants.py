"""Selective course access (`AccessMode.invite`) — grant management + the
enforcement that hangs off `services/course_access_service.py`."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import AccessMode, Course, CourseAccessGrant
from app.models.enrollment import Enrollment, LessonProgress
from app.models.user import User, UserRole
from app.services import course_access_service
from tests.factories import (
    make_course,
    make_enrollment,
    make_lesson_progress,
    make_published_course_with_lesson,
)

pytestmark = pytest.mark.integration


async def _make_student(db: AsyncSession, **overrides: object) -> User:
    from app.services.auth_service import hash_password

    user = User(
        email=f"grantee-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("student-pass-123"),
        full_name="Grantee Student",
        role=UserRole.student,
        is_active=True,
        **overrides,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _set_mode(
    client: AsyncClient, course: Course, mode: str, teacher_token: dict[str, str]
) -> None:
    resp = await client.patch(
        f"/api/v1/courses/{course.id}/access-mode",
        json={"mode": mode},
        cookies=teacher_token,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_restricted"] is (mode == "restricted")


# ── Mode switching ───────────────────────────────────────────────────────────


async def test_switch_to_restricted_backfills_existing_enrollments(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    await make_enrollment(db_session, student_user, course)

    await _set_mode(client, course, "restricted", teacher_token)

    grant = await db_session.scalar(
        select(CourseAccessGrant).where(
            CourseAccessGrant.course_id == course.id,
            CourseAccessGrant.student_id == student_user.id,
        )
    )
    assert grant is not None
    assert grant.granted_by_id == teacher_user.id

    # Already-enrolled student keeps the course in their cabinet.
    resp = await client.get("/api/v1/students/my-courses", cookies=student_token)
    assert resp.status_code == 200
    assert [c["id"] for c in resp.json()] == [str(course.id)]


async def test_switch_back_to_open_restores_code_mode(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(
        db_session, owner=teacher_user, is_published=True, access_code="ABC123"
    )
    await _set_mode(client, course, "restricted", teacher_token)
    await _set_mode(client, course, "open", teacher_token)

    await db_session.refresh(course)
    assert course.access_mode == AccessMode.code


async def test_switch_back_to_open_without_code_falls_back_to_link(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    await _set_mode(client, course, "restricted", teacher_token)
    await _set_mode(client, course, "open", teacher_token)

    await db_session.refresh(course)
    assert course.access_mode == AccessMode.link


async def test_access_mode_requires_ownership(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    resp = await client.patch(
        f"/api/v1/courses/{course.id}/access-mode",
        json={"mode": "restricted"},
        cookies=student_token,
    )
    assert resp.status_code == 403


# ── Enrollment by code ───────────────────────────────────────────────────────


async def test_enroll_by_code_rejected_on_restricted_course(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(
        db_session,
        owner=teacher_user,
        is_published=True,
        access_code="RESTR1",
        access_mode=AccessMode.invite,
    )

    valid = await client.post(
        "/api/v1/students/enroll", json={"access_code": "RESTR1"}, cookies=student_token
    )
    assert valid.status_code == 403

    # Same answer whether the code is right or wrong is only observable for a
    # course the student can address by id — a bad code resolves to no course.
    by_id = await client.post(
        "/api/v1/students/enroll", json={"course_id": str(course.id)}, cookies=student_token
    )
    assert by_id.status_code == 403

    enrolled = await db_session.scalar(
        select(Enrollment.id).where(Enrollment.course_id == course.id)
    )
    assert enrolled is None


async def test_granted_student_may_still_call_enroll(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
    student_token: dict[str, str],
) -> None:
    course = await make_course(
        db_session, owner=teacher_user, is_published=True, access_mode=AccessMode.invite
    )
    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-grants",
        json={"email": student_user.email},
        cookies=teacher_token,
    )
    assert resp.status_code == 201

    enroll = await client.post(
        "/api/v1/students/enroll", json={"course_id": str(course.id)}, cookies=student_token
    )
    assert enroll.status_code == 200


# ── Grant CRUD ───────────────────────────────────────────────────────────────


async def test_add_grant_creates_enrollment_and_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(
        db_session, owner=teacher_user, is_published=True, access_mode=AccessMode.invite
    )

    first = await client.post(
        f"/api/v1/courses/{course.id}/access-grants",
        json={"email": student_user.email},
        cookies=teacher_token,
    )
    second = await client.post(
        f"/api/v1/courses/{course.id}/access-grants",
        json={"email": student_user.email},
        cookies=teacher_token,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["student_id"] == str(student_user.id)
    assert first.json()["email"] == student_user.email

    grants = (
        await db_session.scalars(
            select(CourseAccessGrant).where(CourseAccessGrant.course_id == course.id)
        )
    ).all()
    enrollments = (
        await db_session.scalars(select(Enrollment).where(Enrollment.course_id == course.id))
    ).all()
    assert len(grants) == 1
    assert len(enrollments) == 1


async def test_remove_grant_is_idempotent_and_keeps_progress(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    course, module, lesson = await make_published_course_with_lesson(db_session, teacher_user)
    enrollment = await make_enrollment(db_session, student_user, course)
    await make_lesson_progress(db_session, enrollment, lesson, is_completed=True)
    await _set_mode(client, course, "restricted", teacher_token)

    first = await client.delete(
        f"/api/v1/courses/{course.id}/access-grants/{student_user.id}", cookies=teacher_token
    )
    second = await client.delete(
        f"/api/v1/courses/{course.id}/access-grants/{student_user.id}", cookies=teacher_token
    )
    assert first.status_code == 204
    assert second.status_code == 204

    # Enrollment and its progress survive — the teacher keeps the gradebook row.
    assert await db_session.scalar(select(Enrollment.id).where(Enrollment.id == enrollment.id))
    assert await db_session.scalar(
        select(LessonProgress.id).where(LessonProgress.enrollment_id == enrollment.id)
    )


async def test_grant_to_non_student_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, access_mode=AccessMode.invite)
    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-grants",
        json={"email": teacher_user.email},
        cookies=teacher_token,
    )
    assert resp.status_code == 404


async def test_list_grants_returns_student_profiles(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, access_mode=AccessMode.invite)
    await client.post(
        f"/api/v1/courses/{course.id}/access-grants",
        json={"email": student_user.email},
        cookies=teacher_token,
    )

    resp = await client.get(f"/api/v1/courses/{course.id}/access-grants", cookies=teacher_token)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["student_id"] == str(student_user.id)
    assert body[0]["full_name"] == student_user.full_name


# ── Adding by email ──────────────────────────────────────────────────────────


async def test_add_by_email_is_case_insensitive(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, access_mode=AccessMode.invite)
    student = await _make_student(db_session)

    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-grants",
        json={"email": student.email.upper()},
        cookies=teacher_token,
    )
    assert resp.status_code == 201
    assert resp.json()["student_id"] == str(student.id)


async def test_add_unknown_email_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, access_mode=AccessMode.invite)
    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-grants",
        json={"email": "nobody-here@example.com"},
        cookies=teacher_token,
    )
    assert resp.status_code == 404


async def test_add_soft_deleted_student_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    """A deleted account must be indistinguishable from a nonexistent one."""
    from datetime import datetime, timezone

    course = await make_course(db_session, owner=teacher_user, access_mode=AccessMode.invite)
    deleted = await _make_student(db_session, deleted_at=datetime.now(timezone.utc))

    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-grants",
        json={"email": deleted.email},
        cookies=teacher_token,
    )
    assert resp.status_code == 404


async def test_add_malformed_email_returns_422(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, access_mode=AccessMode.invite)
    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-grants",
        json={"email": "not-an-email"},
        cookies=teacher_token,
    )
    assert resp.status_code == 422


async def test_candidate_search_endpoint_is_gone(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    """Browsing students was removed on purpose (DECISIONS §62) — if someone
    reintroduces it, this fails and they have to read why first."""
    course = await make_course(db_session, owner=teacher_user, access_mode=AccessMode.invite)
    resp = await client.get(
        f"/api/v1/courses/{course.id}/access-grants/search",
        params={"q": "grantee-"},
        cookies=teacher_token,
    )
    # 405, not 404: the path now falls through to DELETE /access-grants/{student_id}.
    assert resp.status_code != 200


# ── Live updates (SSE) ───────────────────────────────────────────────────────


async def test_courses_stream_is_registered_before_course_detail(app: Any) -> None:
    """Route order, not just uniqueness (test_route_shadowing_guard covers that):
    declared after `/courses/{course_id}`, the literal "stream" would be parsed
    as a course id and answer 422 instead of opening the stream."""
    from fastapi.routing import APIRoute

    paths = [r.path for r in app.routes if isinstance(r, APIRoute) and "GET" in r.methods]
    assert paths.index("/api/v1/students/courses/stream") < paths.index(
        "/api/v1/students/courses/{course_id}"
    )


async def test_courses_stream_rejects_teacher(
    client: AsyncClient,
    teacher_token: dict[str, str],
) -> None:
    resp = await client.get("/api/v1/students/courses/stream", cookies=teacher_token)
    assert resp.status_code == 403


async def test_grant_and_revoke_publish_access_change(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The cabinet's stream is only as good as what gets published to it."""
    published: list[tuple[str, str, str]] = []

    async def fake_publish(_redis: Any, student_id: Any, course_id: Any, event: str) -> None:
        published.append((str(student_id), str(course_id), event))

    monkeypatch.setattr(course_access_service, "publish_access_change", fake_publish)

    course = await make_course(
        db_session, owner=teacher_user, is_published=True, access_mode=AccessMode.invite
    )
    await client.post(
        f"/api/v1/courses/{course.id}/access-grants",
        json={"email": student_user.email},
        cookies=teacher_token,
    )
    await client.delete(
        f"/api/v1/courses/{course.id}/access-grants/{student_user.id}",
        cookies=teacher_token,
    )

    assert published == [
        (str(student_user.id), str(course.id), "granted"),
        (str(student_user.id), str(course.id), "revoked"),
    ]


async def test_publish_failure_is_swallowed() -> None:
    """Redis being down must cost live updates, not the teacher's action —
    publishing is best effort and the cabinet still refetches on tab focus."""

    class BrokenRedis:
        async def publish(self, *_args: Any, **_kwargs: Any) -> None:
            raise ConnectionError("redis is down")

    await course_access_service.publish_access_change(
        BrokenRedis(), uuid.uuid4(), uuid.uuid4(), "granted"
    )


# ── Enforcement on every student-facing path ─────────────────────────────────


@pytest.mark.parametrize("granted", [True, False])
async def test_restricted_course_enforced_on_all_student_paths(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    teacher_token: dict[str, str],
    student_token: dict[str, str],
    granted: bool,
) -> None:
    """One enrolled student, one restricted course — every path that used to
    gate on a bare Enrollment must now agree with the grant list."""
    course, module, lesson = await make_published_course_with_lesson(db_session, teacher_user)
    await make_enrollment(db_session, student_user, course)
    await _set_mode(client, course, "restricted", teacher_token)
    if not granted:
        await client.delete(
            f"/api/v1/courses/{course.id}/access-grants/{student_user.id}", cookies=teacher_token
        )

    my_courses = await client.get("/api/v1/students/my-courses", cookies=student_token)
    assert my_courses.status_code == 200
    assert bool(my_courses.json()) is granted

    details = await client.get(f"/api/v1/students/courses/{course.id}", cookies=student_token)
    assert details.status_code == (200 if granted else 403)

    # routers/students.py:get_lesson_for_student
    student_lesson = await client.get(
        f"/api/v1/students/lessons/{lesson.id}", cookies=student_token
    )
    assert student_lesson.status_code == (200 if granted else 403)

    # routers/students.py:_get_progress
    complete = await client.post(
        f"/api/v1/students/lessons/{lesson.id}/complete", cookies=student_token
    )
    assert complete.status_code == (200 if granted else 403)

    # dependencies.require_lesson_access (comments router)
    comments = await client.get(f"/api/v1/lessons/{lesson.id}/comments", cookies=student_token)
    assert comments.status_code == (200 if granted else 403)

    # dependencies.require_lesson_access (assignment_student router)
    assignments = await client.get(
        f"/api/v1/students/lessons/{lesson.id}/assignments", cookies=student_token
    )
    assert assignments.status_code == (200 if granted else 403)

    # routers/quiz_student.py:_ensure_enrolled
    quiz = await client.get(f"/api/v1/students/lessons/{lesson.id}/quiz", cookies=student_token)
    # 404 = access passed, no published quiz on this lesson.
    assert quiz.status_code == (404 if granted else 403)

    dashboard = await client.get("/api/v1/students/dashboard", cookies=student_token)
    assert dashboard.status_code == 200
    assert dashboard.json()["enrolled_courses"] == (1 if granted else 0)
