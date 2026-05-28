"""End-to-end comment routes (list / create / update / delete)."""

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
    make_published_course_with_lesson,
)

pytestmark = pytest.mark.integration


async def _make_enrolled_lesson(
    db: AsyncSession, teacher: User, student: User
):
    course, module, lesson = await make_published_course_with_lesson(db, teacher)
    await make_enrollment(db, student, course)
    return course, module, lesson


async def test_create_then_list_returns_new_comment(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await _make_enrolled_lesson(db_session, teacher_user, student_user)

    create = await client.post(
        f"/api/v1/lessons/{lesson.id}/comments",
        json={"content": "Hello there"},
        cookies=student_token,
    )
    assert create.status_code == 201, create.text
    body = create.json()
    assert body["content"] == "Hello there"
    assert body["author"]["id"] == str(student_user.id)
    assert body["author"]["role"] == "student"
    assert body["is_edited"] is False

    listing = await client.get(
        f"/api/v1/lessons/{lesson.id}/comments",
        cookies=student_token,
    )
    assert listing.status_code == 200
    data = listing.json()
    assert data["total"] == 1
    assert data["items"][0]["id"] == body["id"]


async def test_update_own_comment_marks_edited(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await _make_enrolled_lesson(db_session, teacher_user, student_user)
    created = await client.post(
        f"/api/v1/lessons/{lesson.id}/comments",
        json={"content": "first"},
        cookies=student_token,
    )
    comment_id = created.json()["id"]

    patched = await client.patch(
        f"/api/v1/comments/{comment_id}",
        json={"content": "updated"},
        cookies=student_token,
    )
    assert patched.status_code == 200
    body = patched.json()
    assert body["content"] == "updated"
    assert body["is_edited"] is True


async def test_update_other_users_comment_returns_403(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
    teacher_token: dict[str, str],
) -> None:
    """Teacher-owner can read but cannot patch a student's comment via PATCH
    (PATCH is author-only). DELETE has separate teacher-owner privileges."""
    _, _, lesson = await _make_enrolled_lesson(db_session, teacher_user, student_user)
    created = await client.post(
        f"/api/v1/lessons/{lesson.id}/comments",
        json={"content": "student wrote this"},
        cookies=student_token,
    )
    comment_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/comments/{comment_id}",
        json={"content": "hacked"},
        cookies=teacher_token,
    )
    assert resp.status_code == 403


async def test_delete_own_comment_returns_204(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await _make_enrolled_lesson(db_session, teacher_user, student_user)
    created = await client.post(
        f"/api/v1/lessons/{lesson.id}/comments",
        json={"content": "rm me"},
        cookies=student_token,
    )
    comment_id = created.json()["id"]

    resp = await client.delete(
        f"/api/v1/comments/{comment_id}",
        cookies=student_token,
    )
    assert resp.status_code == 204

    listing = await client.get(
        f"/api/v1/lessons/{lesson.id}/comments",
        cookies=student_token,
    )
    assert listing.json()["total"] == 0


async def test_teacher_owner_can_delete_any_comment(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
    teacher_token: dict[str, str],
) -> None:
    _, _, lesson = await _make_enrolled_lesson(db_session, teacher_user, student_user)
    created = await client.post(
        f"/api/v1/lessons/{lesson.id}/comments",
        json={"content": "by student"},
        cookies=student_token,
    )
    comment_id = created.json()["id"]

    resp = await client.delete(
        f"/api/v1/comments/{comment_id}",
        cookies=teacher_token,
    )
    assert resp.status_code == 204


async def test_other_student_cannot_delete(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    """A second student, enrolled in the same course, cannot delete another
    student's comment (only author or teacher-owner can)."""
    from app.models.user import User as UserModel
    from app.models.user import UserRole
    from app.services.auth_service import hash_password, create_access_token
    import uuid

    other = UserModel(
        email=f"other-{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=hash_password("x"),
        full_name="Other Student",
        role=UserRole.student,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    course, _, lesson = await _make_enrolled_lesson(db_session, teacher_user, student_user)
    await make_enrollment(db_session, other, course)

    created = await client.post(
        f"/api/v1/lessons/{lesson.id}/comments",
        json={"content": "mine"},
        cookies=student_token,
    )
    comment_id = created.json()["id"]

    token, _, _ = create_access_token(other)
    other_token = {"access_token": token, "csrf_token": "test-csrf-fixed-value"}

    resp = await client.delete(
        f"/api/v1/comments/{comment_id}",
        cookies=other_token,
    )
    assert resp.status_code == 403


async def test_non_enrolled_student_gets_403_on_list(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await make_published_course_with_lesson(db_session, teacher_user)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/comments",
        cookies=student_token,
    )
    assert resp.status_code == 403


async def test_missing_lesson_returns_404(
    client: AsyncClient,
    student_token: dict[str, str],
) -> None:
    import uuid

    resp = await client.get(
        f"/api/v1/lessons/{uuid.uuid4()}/comments",
        cookies=student_token,
    )
    assert resp.status_code == 404


async def test_empty_content_returns_422(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await _make_enrolled_lesson(db_session, teacher_user, student_user)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/comments",
        json={"content": "   "},
        cookies=student_token,
    )
    assert resp.status_code == 422


async def test_pagination_limit_offset(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    _, _, lesson = await _make_enrolled_lesson(db_session, teacher_user, student_user)

    for i in range(3):
        await client.post(
            f"/api/v1/lessons/{lesson.id}/comments",
            json={"content": f"msg {i}"},
            cookies=student_token,
        )

    page = await client.get(
        f"/api/v1/lessons/{lesson.id}/comments?limit=2&offset=0",
        cookies=student_token,
    )
    assert page.status_code == 200
    body = page.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
