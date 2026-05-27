"""End-to-end course-CRUD routes."""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import Course
from app.models.lesson import Lesson, Module
from app.models.user import User, UserRole
from app.services.auth_service import create_access_token, hash_password
from tests.factories import make_course, make_lesson, make_module

pytestmark = pytest.mark.integration


async def test_teacher_can_create_course(
    client: AsyncClient, teacher_token: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/courses/",
        json={"title": "Python 101", "description": "Intro"},
        cookies=teacher_token,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == "Python 101"
    assert body["is_published"] is False


async def test_student_cannot_create_course(
    client: AsyncClient, student_token: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/courses/",
        json={"title": "Forbidden"},
        cookies=student_token,
    )
    assert resp.status_code == 403


async def test_teacher_lists_only_own_courses(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    # Create another teacher with an unrelated course.
    other = User(
        email="other@example.com",
        hashed_password=hash_password("pwd-12345678"),
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    await make_course(db_session, owner=teacher_user, title="Mine")
    await make_course(db_session, owner=other, title="Theirs")

    resp = await client.get("/api/v1/courses/", cookies=teacher_token)
    assert resp.status_code == 200
    titles = [c["title"] for c in resp.json()]
    assert "Mine" in titles
    assert "Theirs" not in titles


async def test_delete_course_cascades_to_modules_and_lessons(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.delete(
        f"/api/v1/courses/{course.id}", cookies=teacher_token
    )
    assert resp.status_code == 204

    # Direct DB checks — cascade must have removed the children.
    refetch = await client.get(
        f"/api/v1/courses/{course.id}", cookies=teacher_token
    )
    assert refetch.status_code == 404

    db_session.expire_all()
    module_row = await db_session.execute(
        select(Module).where(Module.id == module.id)
    )
    assert module_row.scalar_one_or_none() is None

    lesson_row = await db_session.execute(
        select(Lesson).where(Lesson.id == lesson.id)
    )
    assert lesson_row.scalar_one_or_none() is None


async def test_publish_toggle_flips_is_published(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, is_published=False)

    r1 = await client.put(
        f"/api/v1/courses/{course.id}/publish", cookies=teacher_token
    )
    assert r1.status_code == 200
    assert r1.json()["is_published"] is True

    r2 = await client.put(
        f"/api/v1/courses/{course.id}/publish", cookies=teacher_token
    )
    assert r2.json()["is_published"] is False


async def test_teacher_cannot_access_another_teachers_course(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_token: dict[str, str],
) -> None:
    other = User(
        email="thief@example.com",
        hashed_password=hash_password("pwd-12345678"),
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    other_course = await make_course(db_session, owner=other)

    resp = await client.get(
        f"/api/v1/courses/{other_course.id}", cookies=teacher_token
    )
    assert resp.status_code == 403


async def test_generate_access_code_sets_code_and_mode(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)

    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-code/generate",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_mode"] == "code"
    assert body["access_code"] is not None
    assert len(body["access_code"]) == 6
    assert body["access_code"].isalnum()


async def test_generate_access_code_regenerates_on_repeat_call(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, access_code="OLD123")

    resp = await client.post(
        f"/api/v1/courses/{course.id}/access-code/generate",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json()["access_code"] != "OLD123"


async def test_generate_access_code_requires_ownership(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_token: dict[str, str],
) -> None:
    other = User(
        email="other-gen@example.com",
        hashed_password=hash_password("pwd-12345678"),
        role=UserRole.teacher,
        is_active=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)
    other_course = await make_course(db_session, owner=other)

    resp = await client.post(
        f"/api/v1/courses/{other_course.id}/access-code/generate",
        cookies=teacher_token,
    )
    assert resp.status_code == 403


async def test_delete_access_code_resets_to_link_mode(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user, access_code="DEL999")

    resp = await client.delete(
        f"/api/v1/courses/{course.id}/access-code",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_code"] is None
    assert body["access_mode"] == "link"
