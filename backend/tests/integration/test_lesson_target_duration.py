"""target_duration_min: range validation and round-trip on lesson routes."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import LESSON_DURATION_MAX_MINUTES
from app.models.user import User
from tests.factories import make_course, make_lesson, make_module

pytestmark = pytest.mark.integration


async def test_create_lesson_accepts_free_form_duration(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)

    resp = await client.post(
        "/api/v1/lessons/",
        json={
            "title": "Timed",
            "module_id": str(module.id),
            "target_duration_min": 7,
        },
        cookies=teacher_token,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["target_duration_min"] == 7
    assert body["duration_sec"] is None


async def test_create_lesson_defaults_to_auto_duration(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)

    resp = await client.post(
        "/api/v1/lessons/",
        json={"title": "Untimed", "module_id": str(module.id)},
        cookies=teacher_token,
    )
    assert resp.status_code == 201
    assert resp.json()["target_duration_min"] is None


@pytest.mark.parametrize("value", [0, -5, LESSON_DURATION_MAX_MINUTES + 1])
async def test_create_lesson_rejects_out_of_range_duration(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    value: int,
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)

    resp = await client.post(
        "/api/v1/lessons/",
        json={"title": "Bad", "module_id": str(module.id), "target_duration_min": value},
        cookies=teacher_token,
    )
    assert resp.status_code == 422


async def test_update_lesson_sets_and_clears_duration(
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
        json={"target_duration_min": 20},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json()["target_duration_min"] == 20

    # Explicit null returns the lesson to "auto".
    resp = await client.put(
        f"/api/v1/lessons/{lesson.id}",
        json={"target_duration_min": None},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json()["target_duration_min"] is None


async def test_update_lesson_rejects_out_of_range_duration(
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
        json={"target_duration_min": 999},
        cookies=teacher_token,
    )
    assert resp.status_code == 422
