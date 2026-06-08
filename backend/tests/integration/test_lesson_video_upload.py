"""Direct video upload to a lesson (no generation pipeline, no AI)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.lesson import CreationMode, Lesson, LessonStatus
from app.models.user import User, UserRole
from app.services.auth_service import hash_password
from tests.conftest import _bearer
from tests.factories import make_course, make_lesson, make_module

pytestmark = pytest.mark.integration

# Minimal MP4 header: a top-level box of type 'ftyp' at offset 4.
_MP4_BYTES = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 16


async def test_upload_video_publishes_and_replaces(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/upload-video",
        files={"file": ("clip.mp4", _MP4_BYTES, "video/mp4")},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "published"
    assert body["creation_mode"] == "video_upload"
    assert body["video_url"]
    first_url = body["video_url"]

    lesson_id = lesson.id
    db_session.expire_all()
    refreshed = await db_session.get(Lesson, lesson_id)
    assert refreshed is not None
    assert refreshed.status == LessonStatus.published
    assert refreshed.creation_mode == CreationMode.video_upload
    assert refreshed.video_url is not None

    # Re-upload replaces the previous video.
    again = await client.post(
        f"/api/v1/lessons/{lesson.id}/upload-video",
        files={"file": ("clip2.webm", b"\x1a\x45\xdf\xa3" + b"\x00" * 20, "video/webm")},
        cookies=teacher_token,
    )
    assert again.status_code == 200
    assert again.json()["status"] == "published"
    assert again.json()["video_url"] != first_url


async def test_upload_video_rejects_wrong_extension(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/upload-video",
        files={"file": ("malware.exe", b"MZ\x90\x00", "application/octet-stream")},
        cookies=teacher_token,
    )
    assert resp.status_code == 400


async def test_upload_video_rejects_corrupt_file(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
) -> None:
    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    # Right extension + content-type, but bytes don't look like a video.
    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/upload-video",
        files={"file": ("clip.mp4", b"not really a video", "video/mp4")},
        cookies=teacher_token,
    )
    assert resp.status_code == 400


async def test_upload_video_too_large_returns_413(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.routers import lessons as lessons_mod

    monkeypatch.setattr(lessons_mod, "MAX_VIDEO_UPLOAD_BYTES", 8)

    course = await make_course(db_session, owner=teacher_user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/upload-video",
        files={"file": ("clip.mp4", _MP4_BYTES, "video/mp4")},
        cookies=teacher_token,
    )
    assert resp.status_code == 413


async def test_upload_video_foreign_lesson_returns_404(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
) -> None:
    # Lesson owned by another teacher; the request comes from a different teacher.
    other = User(
        email=f"other-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("other-pass-123"),
        full_name="Other Teacher",
        role=UserRole.teacher,
        is_active=True,
        email_verified=True,
    )
    db_session.add(other)
    await db_session.commit()
    await db_session.refresh(other)

    course = await make_course(db_session, owner=other)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/upload-video",
        files={"file": ("clip.mp4", _MP4_BYTES, "video/mp4")},
        cookies=_bearer(teacher_user),
    )
    assert resp.status_code == 404


async def test_unverified_teacher_can_upload_video(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    # Direct video upload is NOT gated behind email verification.
    user = User(
        email=f"unverif-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("pass-123456"),
        full_name="Unverified Teacher",
        role=UserRole.teacher,
        is_active=True,
        email_verified=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    course = await make_course(db_session, owner=user)
    module = await make_module(db_session, course)
    lesson = await make_lesson(db_session, module)

    resp = await client.post(
        f"/api/v1/lessons/{lesson.id}/upload-video",
        files={"file": ("clip.mp4", _MP4_BYTES, "video/mp4")},
        cookies=_bearer(user),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"
