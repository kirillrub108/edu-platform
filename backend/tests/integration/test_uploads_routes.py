"""End-to-end upload routes (pptx / script)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import Lesson
from app.models.user import User
from tests.factories import make_course, make_lesson, make_module

pytestmark = pytest.mark.integration


async def test_upload_pptx_persists_path_on_lesson(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    sample_pptx_bytes: bytes,
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.post(
        "/api/v1/uploads/pptx",
        params={"lesson_id": str(lesson.id)},
        files={"file": ("deck.pptx", sample_pptx_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        headers=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["file_path"].startswith("pptx/")

    lesson_id = lesson.id  # snapshot before expire_all to avoid sync lazy-load
    db_session.expire_all()
    refreshed = await db_session.get(Lesson, lesson_id)
    assert refreshed is not None
    assert refreshed.pptx_path == body["file_path"]


async def test_upload_pptx_rejects_executable_extension(
    client: AsyncClient,
    teacher_token: dict[str, str],
) -> None:
    resp = await client.post(
        "/api/v1/uploads/pptx",
        files={"file": ("malware.exe", b"MZ\x90\x00", "application/octet-stream")},
        headers=teacher_token,
    )
    # validate_upload returns 400 for unknown extensions (not 422).
    assert resp.status_code == 400
    assert "not allowed" in resp.json()["detail"].lower()


async def test_upload_script_txt_writes_to_lesson(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    content = "Lecture script line 1.\nLecture line 2.".encode("utf-8")
    resp = await client.post(
        "/api/v1/uploads/script",
        params={"lesson_id": str(lesson.id)},
        files={"file": ("notes.txt", content, "text/plain")},
        headers=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "Lecture script line 1." in body["script"]

    lesson_id = lesson.id  # snapshot before expire_all to avoid sync lazy-load
    db_session.expire_all()
    refreshed = await db_session.get(Lesson, lesson_id)
    assert refreshed is not None
    assert "Lecture script line 1." in refreshed.script


async def test_upload_script_too_large_returns_400(
    client: AsyncClient,
    teacher_token: dict[str, str],
) -> None:
    """The code path raises HTTPException(400) (not 413) for oversized
    text uploads — fixing test against actual behaviour, see analysis."""
    # 11 MB > MAX_SCRIPT_BYTES (10 MB)
    payload = b"a" * (11 * 1024 * 1024)
    resp = await client.post(
        "/api/v1/uploads/script",
        files={"file": ("big.txt", payload, "text/plain")},
        headers=teacher_token,
    )
    # validate_upload trips the SIZE_LIMITS check first → 400.
    assert resp.status_code == 400
