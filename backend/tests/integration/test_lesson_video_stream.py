"""Authorised video-stream endpoints: access model + delivery modes.

/stream runs the normal enrollment/visibility guard, then hands the byte
transfer off — never streaming it through Python:
  * S3 (primary): 302 → presigned URL.
  * local + nginx: empty body + X-Accel-Redirect.
  * local + no nginx (dev): 302 → signed absolute /files URL (loaded directly).
The serializers pick the player URL per mode via ``video_playback_url``: a
bearer-signed /files URL in dev (cross-origin direct load), /stream in prod. The
old /files/videos/* path is blocked in the prod verify endpoint.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.lesson_video import LessonVideo
from app.models.user import User
from app.routers import lessons as lessons_mod
from tests.factories import (
    make_course,
    make_enrollment,
    make_lesson,
    make_module,
)

pytestmark = pytest.mark.integration

# A stored video_url is always a signed /files/videos/* URL — the endpoint only
# extracts the relative key from it, so a fixed value is enough for these tests.
_VIDEO_URL = "http://testserver/files/videos/abc/clip.mp4?uid=1&expires=1&sig=deadbeef"
_VIDEO_KEY = "videos/abc/clip.mp4"


async def _published_lesson(db: AsyncSession, owner: User, **lesson_overrides):
    course = await make_course(db, owner=owner, is_published=True)
    module = await make_module(db, course)
    lesson = await make_lesson(db, module, video_url=_VIDEO_URL, **lesson_overrides)
    return course, module, lesson


# ── Access model ─────────────────────────────────────────────────────────────


async def test_stream_non_enrolled_student_403(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    _course, _module, lesson = await _published_lesson(db_session, teacher_user)
    # No enrollment created.
    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/video/stream", cookies=student_token
    )
    assert resp.status_code == 403


async def test_stream_unpublished_lesson_404_for_enrolled(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course, _module, lesson = await _published_lesson(
        db_session, teacher_user, is_published=False
    )
    await make_enrollment(db_session, student_user, course)
    # Draft lesson hides with 404 (never 403) so the draft isn't revealed.
    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/video/stream", cookies=student_token
    )
    assert resp.status_code == 404


# ── Delivery modes ───────────────────────────────────────────────────────────


async def test_stream_xaccel_local(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course, _module, lesson = await _published_lesson(db_session, teacher_user)
    await make_enrollment(db_session, student_user, course)

    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(lessons_mod, "VIDEO_XACCEL_ENABLED", True)
    monkeypatch.setattr(lessons_mod.storage_service,"exists", lambda rel: True)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/video/stream", cookies=student_token
    )
    assert resp.status_code == 200
    # Body-less; nginx serves the bytes from the internal location.
    assert resp.content == b""
    assert resp.headers["x-accel-redirect"] == f"/protected-media/{_VIDEO_KEY}"
    assert resp.headers["content-type"] == "video/mp4"


async def test_stream_s3_redirects_to_presigned(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course, _module, lesson = await _published_lesson(db_session, teacher_user)
    await make_enrollment(db_session, student_user, course)

    presigned = "https://s3.example.test/bucket/videos/abc/clip.mp4?X-Amz-Signature=xyz"
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "S3_BUCKET_NAME", "bucket")
    monkeypatch.setattr(
        lessons_mod.storage_service, "presign_stream_url", lambda rel, ttl: presigned
    )

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/video/stream", cookies=student_token
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == presigned
    # Bearer URL must not be retained by any shared cache.
    assert resp.headers["cache-control"] == "no-store"


async def test_stream_s3_missing_bucket_500(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course, _module, lesson = await _published_lesson(db_session, teacher_user)
    await make_enrollment(db_session, student_user, course)

    # provider=s3 but no credentials → explicit 500, never a silent fail.
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(settings, "S3_BUCKET_NAME", "")

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/video/stream", cookies=student_token
    )
    assert resp.status_code == 500


async def test_stream_dev_fallback_fileresponse(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    course, _module, lesson = await _published_lesson(db_session, teacher_user)
    await make_enrollment(db_session, student_user, course)

    # local + nginx off → 302 to a signed absolute /files URL so the browser
    # fetches bytes directly from the backend (the Nuxt dev proxy can't relay a
    # streamed 206). No FileResponse streamed through Python.
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(lessons_mod, "VIDEO_XACCEL_ENABLED", False)
    monkeypatch.setattr(lessons_mod.storage_service, "exists", lambda rel: True)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/video/stream",
        cookies=student_token,
        follow_redirects=False,
    )
    assert resp.status_code == 302
    loc = resp.headers["location"]
    # Signed absolute /files URL for the same key, bearer-style (uid + sig).
    assert f"/files/{_VIDEO_KEY}" in loc
    assert "sig=" in loc and "uid=" in loc
    assert resp.headers["cache-control"] == "no-store"


# ── Specific-render endpoint ─────────────────────────────────────────────────


async def _make_render(db: AsyncSession, lesson, *, is_published: bool) -> LessonVideo:
    video = LessonVideo(
        lesson_id=lesson.id,
        video_url=_VIDEO_URL,
        voice="baya",
        creation_mode="presentation_and_text",
        is_published=is_published,
    )
    db.add(video)
    await db.commit()
    await db.refresh(video)
    return video


async def test_render_draft_hidden_from_student_404(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    student_user: User,
    student_token: dict[str, str],
) -> None:
    course, _module, lesson = await _published_lesson(db_session, teacher_user)
    await make_enrollment(db_session, student_user, course)
    video = await _make_render(db_session, lesson, is_published=False)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/videos/{video.id}/stream",
        cookies=student_token,
    )
    assert resp.status_code == 404


async def test_render_draft_visible_to_owner(
    client: AsyncClient,
    db_session: AsyncSession,
    teacher_user: User,
    teacher_token: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _course, _module, lesson = await _published_lesson(db_session, teacher_user)
    video = await _make_render(db_session, lesson, is_published=False)

    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(lessons_mod, "VIDEO_XACCEL_ENABLED", True)
    monkeypatch.setattr(lessons_mod.storage_service,"exists", lambda rel: True)

    resp = await client.get(
        f"/api/v1/lessons/{lesson.id}/videos/{video.id}/stream",
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.headers["x-accel-redirect"] == f"/protected-media/{_VIDEO_KEY}"


# ── Old signed path: open (bearer) in dev, blocked in prod ───────────────────


async def test_dev_files_route_serves_videos_as_signed_urls(
    client: AsyncClient,
) -> None:
    # The dev route (serve_file, registered when SERVE_STATIC_VIA_NGINX=false) is
    # the 302 target for the /stream endpoint, so /files/videos/* stays reachable
    # and is signature-gated exactly like any other asset (bad sig → 403, not a
    # blanket block).
    video = await client.get(
        "/files/videos/abc/clip.mp4?uid=1&expires=9999999999&sig=deadbeef"
    )
    assert video.status_code == 403
    cover = await client.get(
        "/files/covers/pic.png?uid=1&expires=9999999999&sig=deadbeef"
    )
    assert cover.status_code == 403


# ── Serializer URL selection: dev (signed /files) vs prod (/stream) ──────────


def test_video_playback_url_dev_returns_signed_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lid, vid = uuid4(), uuid4()
    monkeypatch.setattr(lessons_mod, "_VIDEO_DIRECT_SIGNED", True)
    url = lessons_mod.video_playback_url(lid, vid, _VIDEO_URL, "user-1")
    assert url is not None
    assert f"/files/{_VIDEO_KEY}" in url and "sig=" in url


def test_video_playback_url_prod_returns_stream_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lid, vid = uuid4(), uuid4()
    monkeypatch.setattr(lessons_mod, "_VIDEO_DIRECT_SIGNED", False)
    assert (
        lessons_mod.video_playback_url(lid, vid, _VIDEO_URL, "u")
        == f"/api/v1/lessons/{lid}/videos/{vid}/stream"
    )
    assert (
        lessons_mod.video_playback_url(lid, None, _VIDEO_URL, "u")
        == f"/api/v1/lessons/{lid}/video/stream"
    )
    assert lessons_mod.video_playback_url(lid, None, None, "u") is None


async def test_prod_verify_endpoint_blocks_videos_even_with_valid_signature() -> None:
    # In prod nginx serves /files/* and only calls verify_file_signature. There a
    # video path is refused (403) even with a VALID signature, so the only way to
    # video bytes is the enrollment-checked /stream endpoint (X-Accel).
    from fastapi import HTTPException

    from app.routers.files import verify_file_signature
    from app.services.signed_url_service import generate_signed_url

    class _Req:
        def __init__(self, uri: str) -> None:
            self.headers = {"X-Original-URI": uri}

    video_signed = generate_signed_url("videos/abc/clip.mp4", "uid1")
    with pytest.raises(HTTPException) as exc:
        await verify_file_signature(_Req(video_signed))  # type: ignore[arg-type]
    assert exc.value.status_code == 403

    # A validly-signed non-video path still verifies (200) — the block is scoped.
    cover_signed = generate_signed_url("covers/pic.png", "uid1")
    resp = await verify_file_signature(_Req(cover_signed))  # type: ignore[arg-type]
    assert resp.status_code == 200
