"""detail_level: validation, default, and round-trip on the lesson routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from tests.factories import make_course, make_lesson, make_module

pytestmark = pytest.mark.integration


async def test_create_lesson_defaults_to_auto_detail(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)

    resp = await client.post(
        "/api/v1/lessons/",
        json={"title": "Untuned", "module_id": str(module.id)},
        cookies=teacher_token,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["detail_level"] == "auto"
    assert body["duration_sec"] is None


@pytest.mark.parametrize("level", ["brief", "auto", "high"])
async def test_create_lesson_accepts_every_level(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    level: str,
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)

    resp = await client.post(
        "/api/v1/lessons/",
        json={"title": "Tuned", "module_id": str(module.id), "detail_level": level},
        cookies=teacher_token,
    )
    assert resp.status_code == 201
    assert resp.json()["detail_level"] == level


@pytest.mark.parametrize("level", ["", "medium", "HIGH", "15", None])
async def test_create_lesson_rejects_unknown_level(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    level: object,
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)

    resp = await client.post(
        "/api/v1/lessons/",
        json={"title": "Bad", "module_id": str(module.id), "detail_level": level},
        cookies=teacher_token,
    )
    assert resp.status_code == 422


async def test_update_lesson_changes_detail_level(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.put(
        f"/api/v1/lessons/{lesson.id}",
        json={"detail_level": "high"},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json()["detail_level"] == "high"


async def test_update_lesson_rejects_unknown_level(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.put(
        f"/api/v1/lessons/{lesson.id}",
        json={"detail_level": "verbose"},
        cookies=teacher_token,
    )
    assert resp.status_code == 422
