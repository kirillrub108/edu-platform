"""Module/lesson publish flags: effective student visibility + idempotency.

Effective visibility for an enrolled student = module.is_published AND
lesson.is_published. course.is_published gates discovery/new-enroll only — an
already-enrolled student keeps access after the course is unpublished. A draft
module/lesson still hides the element from students (and direct-by-id access
404s), while owners keep seeing everything. The flags are independent —
unpublishing a parent never clears a child's flag.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from tests.factories import (
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
)

pytestmark = pytest.mark.integration


# ── Student visibility (the AND-chain) ───────────────────────────────────────


async def test_draft_module_hides_its_lessons_from_student(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course, is_published=False)
    # Lesson itself is published, but its parent module is a draft → hidden.
    lesson = await make_lesson(db_session, module, is_published=True)
    await make_enrollment(db_session, student_user, course)

    detail = await client.get(
        f"/api/v1/students/courses/{course.id}", cookies=student_token
    )
    assert detail.status_code == 200
    assert detail.json()["modules"] == []

    # Direct-by-id access must not leak the draft.
    direct = await client.get(
        f"/api/v1/students/lessons/{lesson.id}", cookies=student_token
    )
    assert direct.status_code == 404


async def test_draft_lesson_hidden_but_module_still_listed(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course, is_published=True)
    lesson = await make_lesson(db_session, module, is_published=False)
    await make_enrollment(db_session, student_user, course)

    detail = await client.get(
        f"/api/v1/students/courses/{course.id}", cookies=student_token
    )
    assert detail.status_code == 200
    modules = detail.json()["modules"]
    assert len(modules) == 1
    assert modules[0]["lessons"] == []

    direct = await client.get(
        f"/api/v1/students/lessons/{lesson.id}", cookies=student_token
    )
    assert direct.status_code == 404


async def test_fully_published_chain_is_visible_to_student(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course, is_published=True)
    lesson = await make_lesson(db_session, module, is_published=True)
    await make_enrollment(db_session, student_user, course)

    detail = await client.get(
        f"/api/v1/students/courses/{course.id}", cookies=student_token
    )
    assert detail.status_code == 200
    modules = detail.json()["modules"]
    assert [l["id"] for l in modules[0]["lessons"]] == [str(lesson.id)]

    direct = await client.get(
        f"/api/v1/students/lessons/{lesson.id}", cookies=student_token
    )
    assert direct.status_code == 200


async def test_unpublished_course_keeps_enrolled_student_access(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    """Decoupling: course.is_published no longer gates enrolled-student access.

    Module + lesson are published, the course is NOT — an already-enrolled
    student still sees the lesson in the tree and can open it directly.
    """
    course = await make_course(db_session, owner=teacher_user, is_published=False)
    module = await make_module(db_session, course, is_published=True)
    lesson = await make_lesson(db_session, module, is_published=True)
    await make_enrollment(db_session, student_user, course)

    detail = await client.get(
        f"/api/v1/students/courses/{course.id}", cookies=student_token
    )
    assert detail.status_code == 200
    modules = detail.json()["modules"]
    assert [l["id"] for l in modules[0]["lessons"]] == [str(lesson.id)]

    direct = await client.get(
        f"/api/v1/students/lessons/{lesson.id}", cookies=student_token
    )
    assert direct.status_code == 200


async def test_unpublished_course_with_draft_module_still_hidden(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    """Content gate survives: an unpublished module hides the lesson even from an
    enrolled student, regardless of course.is_published (a deliberate teacher act)."""
    course = await make_course(db_session, owner=teacher_user, is_published=False)
    module = await make_module(db_session, course, is_published=False)
    lesson = await make_lesson(db_session, module, is_published=True)
    await make_enrollment(db_session, student_user, course)

    detail = await client.get(
        f"/api/v1/students/courses/{course.id}", cookies=student_token
    )
    assert detail.status_code == 200
    assert detail.json()["modules"] == []

    direct = await client.get(
        f"/api/v1/students/lessons/{lesson.id}", cookies=student_token
    )
    assert direct.status_code == 404


async def test_non_enrolled_student_still_forbidden(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    """Enrollment check is unchanged: a non-enrolled student gets 403, even on a
    fully published chain."""
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course, is_published=True)
    lesson = await make_lesson(db_session, module, is_published=True)

    detail = await client.get(
        f"/api/v1/students/courses/{course.id}", cookies=student_token
    )
    assert detail.status_code == 403

    direct = await client.get(
        f"/api/v1/students/lessons/{lesson.id}", cookies=student_token
    )
    assert direct.status_code == 403


async def test_owner_sees_drafts_with_flags(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course, is_published=False)
    lesson = await make_lesson(db_session, module, is_published=False)

    resp = await client.get(f"/api/v1/courses/{course.id}", cookies=teacher_token)
    assert resp.status_code == 200
    modules = resp.json()["modules"]
    assert modules[0]["is_published"] is False
    assert modules[0]["lessons"][0]["id"] == str(lesson.id)
    assert modules[0]["lessons"][0]["is_published"] is False


# ── Idempotency + independence of publish/unpublish ──────────────────────────


async def test_module_publish_unpublish_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course, is_published=False)
    base = f"/api/v1/courses/{course.id}/modules/{module.id}"

    for _ in range(2):
        r = await client.post(f"{base}/publish", cookies=teacher_token)
        assert r.status_code == 200
        assert r.json()["is_published"] is True

    for _ in range(2):
        r = await client.post(f"{base}/unpublish", cookies=teacher_token)
        assert r.status_code == 200
        assert r.json()["is_published"] is False


async def test_lesson_publish_unpublish_is_idempotent(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course, is_published=True)
    lesson = await make_lesson(db_session, module, is_published=False)
    base = f"/api/v1/lessons/{lesson.id}"

    for _ in range(2):
        r = await client.post(f"{base}/publish", cookies=teacher_token)
        assert r.status_code == 200
        assert r.json()["is_published"] is True

    for _ in range(2):
        r = await client.post(f"{base}/unpublish", cookies=teacher_token)
        assert r.status_code == 200
        assert r.json()["is_published"] is False


async def test_unpublishing_module_keeps_lesson_flag(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    """Flags are independent: hiding is a read-time AND, not a cascade."""
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course, is_published=True)
    await make_lesson(db_session, module, is_published=True)

    await client.post(
        f"/api/v1/courses/{course.id}/modules/{module.id}/unpublish",
        cookies=teacher_token,
    )

    resp = await client.get(f"/api/v1/courses/{course.id}", cookies=teacher_token)
    module_out = resp.json()["modules"][0]
    assert module_out["is_published"] is False
    # The child lesson's own flag is untouched.
    assert module_out["lessons"][0]["is_published"] is True
