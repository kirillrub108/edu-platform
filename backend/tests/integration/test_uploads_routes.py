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
        cookies=teacher_token,
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
        cookies=teacher_token,
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
        cookies=teacher_token,
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
        cookies=teacher_token,
    )
    # validate_upload trips the SIZE_LIMITS check first → 400.
    assert resp.status_code == 400


async def test_upload_pptx_unauthenticated_returns_401(
    client: AsyncClient,
    sample_pptx_bytes: bytes,
) -> None:
    resp = await client.post(
        "/api/v1/uploads/pptx",
        files={"file": ("deck.pptx", sample_pptx_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
    )
    assert resp.status_code == 401


async def test_upload_pptx_without_lesson_id_returns_file_path(
    client: AsyncClient,
    teacher_token: dict[str, str],
    sample_pptx_bytes: bytes,
) -> None:
    """Upload without lesson_id saves the file but doesn't attach it to any lesson."""
    resp = await client.post(
        "/api/v1/uploads/pptx",
        files={"file": ("deck.pptx", sample_pptx_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "file_path" in body
    assert "file_url" in body


async def test_upload_script_pdf_returns_extracted_text(
    client: AsyncClient,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import uploads as uploads_mod

    monkeypatch.setattr(uploads_mod, "_extract_pdf_text", lambda _bytes: "extracted pdf text")

    resp = await client.post(
        "/api/v1/uploads/script",
        files={"file": ("lecture.pdf", b"%PDF-1.4 fake content", "application/pdf")},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["script"] == "extracted pdf text"
    assert body["chars"] == len("extracted pdf text")


async def test_upload_script_unauthenticated_returns_401(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/uploads/script",
        files={"file": ("notes.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 401


async def test_upload_cover_returns_file_url(
    client: AsyncClient,
    teacher_token: dict[str, str],
) -> None:
    resp = await client.post(
        "/api/v1/uploads/cover",
        files={"file": ("photo.jpg", b"fake-jpeg-data", "image/jpeg")},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "file_url" in body
    assert "covers/" in body["file_url"]


async def test_upload_cover_rejects_wrong_type(
    client: AsyncClient,
    teacher_token: dict[str, str],
) -> None:
    resp = await client.post(
        "/api/v1/uploads/cover",
        files={"file": ("doc.pdf", b"%PDF-fake", "application/pdf")},
        cookies=teacher_token,
    )
    assert resp.status_code == 400
    assert "JPEG" in resp.json()["detail"] or "PNG" in resp.json()["detail"]


async def test_upload_cover_rejects_oversized(
    client: AsyncClient,
    teacher_token: dict[str, str],
) -> None:
    payload = b"x" * (6 * 1024 * 1024)  # 6 MB > 5 MB limit
    resp = await client.post(
        "/api/v1/uploads/cover",
        files={"file": ("big.jpg", payload, "image/jpeg")},
        cookies=teacher_token,
    )
    assert resp.status_code == 400


async def test_upload_cover_unauthenticated_returns_401(
    client: AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/uploads/cover",
        files={"file": ("photo.jpg", b"fake-jpeg-data", "image/jpeg")},
    )
    assert resp.status_code == 401


async def test_upload_pptx_with_refresh_token_returns_401(
    client: AsyncClient,
    teacher_user: Any,
    sample_pptx_bytes: bytes,
) -> None:
    """The HTTP auth layer (get_current_token_payload) must reject refresh tokens
    used as Bearer credentials — this is the type-check that decode_token itself
    does not perform."""
    import uuid
    from datetime import datetime, timedelta, timezone

    from app.services.auth_service import create_refresh_token

    family = str(uuid.uuid4())
    absolute = datetime.now(timezone.utc) + timedelta(days=14)
    refresh_token, _, _ = create_refresh_token(
        str(teacher_user.id), family, sliding_days=14, absolute_expires_at=absolute
    )
    from tests.conftest import _TEST_CSRF
    resp = await client.post(
        "/api/v1/uploads/pptx",
        files={"file": ("deck.pptx", sample_pptx_bytes, "application/vnd.openxmlformats-officedocument.presentationml.presentation")},
        cookies={"access_token": refresh_token, "csrf_token": _TEST_CSRF},
    )
    assert resp.status_code == 401
