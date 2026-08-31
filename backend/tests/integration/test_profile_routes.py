"""Public profile visibility matrix, own settings, and avatar upload."""

from __future__ import annotations

from io import BytesIO
from urllib.parse import parse_qs, unquote, urlparse

import pytest
from httpx import AsyncClient
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import ProfileVisibility, User, UserRole
from app.services.auth_service import create_access_token, hash_password
from app.services.signed_url_service import verify_signed_url
from app.services.storage_service import storage_service
from tests.factories import make_course, make_enrollment, make_lesson, make_module

pytestmark = pytest.mark.integration


def _png(size: tuple[int, int] = (300, 200), color: tuple[int, int, int] = (200, 40, 40)) -> bytes:
    buf = BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


async def _cookies_for(user: User) -> dict[str, str]:
    token, _, _ = create_access_token(user)
    return {"access_token": token, "csrf_token": "test-csrf"}


async def _make_user(
    db: AsyncSession,
    *,
    role: UserRole,
    visibility: ProfileVisibility = ProfileVisibility.public,
    show_stats: bool = True,
    full_name: str = "Профиль Тестовый",
) -> User:
    import uuid

    user = User(
        email=f"{uuid.uuid4().hex}@example.com",
        hashed_password=hash_password("password123"),
        full_name=full_name,
        role=role,
        email_verified=True,
        profile_visibility=visibility,
        show_profile_stats=show_stats,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


def _profile_url(user: User) -> str:
    return f"/api/v1/users/{user.id}/profile"


# ── Visibility matrix ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("visibility", "viewer", "expected"),
    [
        # public — everyone, anonymous included
        (ProfileVisibility.public, "anonymous", 200),
        (ProfileVisibility.public, "stranger", 200),
        (ProfileVisibility.public, "owner", 200),
        # authenticated — signed in only
        (ProfileVisibility.authenticated, "anonymous", 404),
        (ProfileVisibility.authenticated, "stranger", 200),
        (ProfileVisibility.authenticated, "owner", 200),
        # private — owner only (the enrolling teacher is covered separately)
        (ProfileVisibility.private, "anonymous", 404),
        (ProfileVisibility.private, "stranger", 404),
        (ProfileVisibility.private, "owner", 200),
    ],
)
async def test_visibility_matrix(
    client: AsyncClient,
    db_session: AsyncSession,
    visibility: ProfileVisibility,
    viewer: str,
    expected: int,
) -> None:
    target = await _make_user(db_session, role=UserRole.student, visibility=visibility)

    if viewer == "anonymous":
        cookies: dict[str, str] = {}
    elif viewer == "owner":
        cookies = await _cookies_for(target)
    else:
        stranger = await _make_user(db_session, role=UserRole.student)
        cookies = await _cookies_for(stranger)

    resp = await client.get(_profile_url(target), cookies=cookies)
    assert resp.status_code == expected


async def test_private_profile_visible_to_enrolling_teacher(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    student = await _make_user(
        db_session, role=UserRole.student, visibility=ProfileVisibility.private
    )
    course = await make_course(db_session, owner=teacher_user)
    await make_enrollment(db_session, course=course, student=student)

    resp = await client.get(_profile_url(student), cookies=await _cookies_for(teacher_user))
    assert resp.status_code == 200


async def test_private_profile_hidden_from_unrelated_teacher(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    """Being a teacher is not enough — only a teacher of this student's courses."""
    student = await _make_user(
        db_session, role=UserRole.student, visibility=ProfileVisibility.private
    )
    resp = await client.get(_profile_url(student), cookies=await _cookies_for(teacher_user))
    assert resp.status_code == 404


async def test_hidden_profile_is_404_not_403(client: AsyncClient, db_session: AsyncSession) -> None:
    """404 so the API never confirms a hidden account exists — same rule as
    unpublished lessons."""
    target = await _make_user(
        db_session, role=UserRole.student, visibility=ProfileVisibility.private
    )
    hidden = await client.get(_profile_url(target))
    missing = await client.get("/api/v1/users/00000000-0000-0000-0000-000000000000/profile")
    assert hidden.status_code == missing.status_code == 404


async def test_soft_deleted_profile_hidden_even_from_owner(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    from app.services.auth_service import soft_delete_user

    target = await _make_user(db_session, role=UserRole.teacher)
    cookies = await _cookies_for(target)
    soft_delete_user(target)
    await db_session.commit()

    assert (await client.get(_profile_url(target), cookies=cookies)).status_code == 404


# ── Stats toggle ─────────────────────────────────────────────────────────────


async def test_stats_hidden_but_identity_and_avatar_remain(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    target = await _make_user(
        db_session,
        role=UserRole.teacher,
        visibility=ProfileVisibility.public,
        show_stats=False,
        full_name="Мария Иванова",
    )
    target.bio = "Читаю курс по алгебре"
    target.avatar_external_url = "https://lh3.googleusercontent.com/a/xyz"
    course = await make_course(db_session, owner=target, is_published=True)
    await db_session.commit()

    body = (await client.get(_profile_url(target))).json()

    assert body["teacher_stats"] is None
    assert body["student_stats"] is None
    # Identity, avatar and the course list survive — only numbers are cut.
    assert body["full_name"] == "Мария Иванова"
    assert body["bio"] == "Читаю курс по алгебре"
    assert body["avatar_url"] == "https://lh3.googleusercontent.com/a/xyz"
    assert [c["id"] for c in body["courses"]] == [str(course.id)]


async def test_owner_sees_own_stats_despite_toggle(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    target = await _make_user(db_session, role=UserRole.teacher, show_stats=False)
    body = (await client.get(_profile_url(target), cookies=await _cookies_for(target))).json()

    assert body["is_owner"] is True
    assert body["teacher_stats"] is not None
    assert body["show_profile_stats"] is False


async def test_profile_never_exposes_email(client: AsyncClient, db_session: AsyncSession) -> None:
    target = await _make_user(db_session, role=UserRole.teacher)
    body = (await client.get(_profile_url(target), cookies=await _cookies_for(target))).json()
    assert "email" not in body


async def test_visibility_settings_are_owner_only(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    target = await _make_user(db_session, role=UserRole.teacher)
    stranger = await _make_user(db_session, role=UserRole.student)

    body = (await client.get(_profile_url(target), cookies=await _cookies_for(stranger))).json()
    assert body["is_owner"] is False
    assert body["profile_visibility"] is None
    assert body["show_profile_stats"] is None


# ── Profile contents ─────────────────────────────────────────────────────────


async def test_teacher_profile_lists_only_published_courses(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    teacher = await _make_user(db_session, role=UserRole.teacher)
    published = await make_course(db_session, owner=teacher, is_published=True)
    await make_course(db_session, owner=teacher, is_published=False)
    module = await make_module(db_session, published, is_published=True)
    await make_lesson(db_session, module, is_published=True)
    await db_session.commit()

    body = (await client.get(_profile_url(teacher))).json()

    assert [c["id"] for c in body["courses"]] == [str(published.id)]
    assert body["courses"][0]["lessons_count"] == 1
    assert body["teacher_stats"]["courses_count"] == 1
    assert body["teacher_stats"]["lessons_count"] == 1


async def test_teacher_stats_count_enrolled_students(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    teacher = await _make_user(db_session, role=UserRole.teacher)
    course = await make_course(db_session, owner=teacher, is_published=True)
    for _ in range(3):
        student = await _make_user(db_session, role=UserRole.student)
        await make_enrollment(db_session, course=course, student=student)
    await db_session.commit()

    body = (await client.get(_profile_url(teacher))).json()
    assert body["teacher_stats"]["students_count"] == 3


async def test_student_profile_reports_course_progress(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User
) -> None:
    from tests.factories import make_lesson_progress

    student = await _make_user(
        db_session, role=UserRole.student, visibility=ProfileVisibility.public
    )
    course = await make_course(db_session, owner=teacher_user, is_published=True)
    module = await make_module(db_session, course, is_published=True)
    first = await make_lesson(db_session, module, is_published=True)
    await make_lesson(db_session, module, is_published=True)
    enrollment = await make_enrollment(db_session, course=course, student=student)
    await make_lesson_progress(db_session, enrollment=enrollment, lesson=first, is_completed=True)
    await db_session.commit()

    body = (await client.get(_profile_url(student))).json()

    assert len(body["courses"]) == 1
    assert body["courses"][0]["lessons_count"] == 2
    assert body["courses"][0]["progress_percent"] == 50.0
    assert body["student_stats"]["completed_lessons"] == 1


# ── Own settings ─────────────────────────────────────────────────────────────


async def test_patch_profile_and_privacy(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User, teacher_token: dict
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/profile",
        json={"full_name": "Новое Имя", "bio": "  Био с пробелами  "},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Новое Имя"
    assert resp.json()["bio"] == "Био с пробелами"

    resp = await client.patch(
        "/api/v1/users/me/privacy",
        json={"profile_visibility": "private", "show_profile_stats": False},
        cookies=teacher_token,
    )
    assert resp.status_code == 200
    assert resp.json() == {"profile_visibility": "private", "show_profile_stats": False}


async def test_bio_length_is_capped(
    client: AsyncClient, teacher_user: User, teacher_token: dict
) -> None:
    resp = await client.patch(
        "/api/v1/users/me/profile", json={"bio": "x" * 5000}, cookies=teacher_token
    )
    assert resp.status_code == 422


async def test_profile_endpoints_require_auth(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/users/me/profile")).status_code == 401
    assert (await client.get("/api/v1/users/me/privacy")).status_code == 401


# ── Avatar ───────────────────────────────────────────────────────────────────


async def test_avatar_upload_happy_path(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User, teacher_token: dict
) -> None:
    resp = await client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("me.png", _png(), "image/png")},
        cookies=teacher_token,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["avatar_url"]

    user_id = teacher_user.id
    db_session.expire_all()
    refreshed = await db_session.get(User, user_id)
    assert refreshed.avatar_image_path.startswith(f"avatars/{user_id}/")
    # Stored normalized, always as one format regardless of what was uploaded.
    assert refreshed.avatar_image_path.endswith(".webp")
    assert storage_service.exists(refreshed.avatar_image_path)


async def test_uploaded_avatar_survives_in_auth_me(
    client: AsyncClient, teacher_user: User, teacher_token: dict
) -> None:
    """The upload response is not the only place the avatar has to appear: the
    SPA refills its store from /auth/me on every reload, so a null there is
    indistinguishable from "no avatar" and the picture silently disappears."""
    await client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("me.png", _png(), "image/png")},
        cookies=teacher_token,
    )

    resp = await client.get("/api/v1/auth/me", cookies=teacher_token)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["avatar_url"], "avatar must survive a fresh session probe"
    # The two source columns stay server-side; clients see one ready URL.
    assert "avatar_image_path" not in body
    assert "avatar_external_url" not in body


async def test_avatar_rejects_oversized_file(
    client: AsyncClient, teacher_user: User, teacher_token: dict
) -> None:
    # A real PNG (passes the signature check) that is over the 2 MB cap.
    big = _png((3000, 3000)) + b"\x00" * (2 * 1024 * 1024)
    resp = await client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("big.png", big, "image/png")},
        cookies=teacher_token,
    )
    assert resp.status_code == 400


async def test_avatar_rejects_svg(
    client: AsyncClient, teacher_user: User, teacher_token: dict
) -> None:
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    resp = await client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("evil.svg", svg, "image/svg+xml")},
        cookies=teacher_token,
    )
    assert resp.status_code == 400


async def test_avatar_rejects_spoofed_content_type(
    client: AsyncClient, teacher_user: User, teacher_token: dict
) -> None:
    """An SVG claiming image/png with a .png name — only the real signature
    check stops this, and /files/* would serve it inline."""
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    resp = await client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("evil.png", svg, "image/png")},
        cookies=teacher_token,
    )
    assert resp.status_code == 400


async def test_replacing_avatar_removes_the_old_file(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User, teacher_token: dict
) -> None:
    await client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("one.png", _png(color=(10, 10, 200)), "image/png")},
        cookies=teacher_token,
    )
    user_id = teacher_user.id
    db_session.expire_all()
    first_path = (await db_session.get(User, user_id)).avatar_image_path

    await client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("two.png", _png(color=(200, 10, 10)), "image/png")},
        cookies=teacher_token,
    )
    db_session.expire_all()
    second_path = (await db_session.get(User, user_id)).avatar_image_path

    assert second_path != first_path
    assert not storage_service.exists(first_path), "old avatar must not be orphaned"
    assert storage_service.exists(second_path)


async def test_delete_avatar_falls_back_to_provider_picture(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User, teacher_token: dict
) -> None:
    teacher_user.avatar_external_url = "https://lh3.googleusercontent.com/a/provider"
    await db_session.commit()

    await client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("me.png", _png(), "image/png")},
        cookies=teacher_token,
    )
    user_id = teacher_user.id
    db_session.expire_all()
    uploaded_path = (await db_session.get(User, user_id)).avatar_image_path

    resp = await client.delete("/api/v1/users/me/avatar", cookies=teacher_token)

    assert resp.status_code == 200
    # Deleting the upload reveals the provider's picture again — that IS the
    # "revert to my Google avatar" action; there is no separate switch.
    assert resp.json()["avatar_url"] == "https://lh3.googleusercontent.com/a/provider"
    assert not storage_service.exists(uploaded_path)

    db_session.expire_all()
    assert (await db_session.get(User, user_id)).avatar_image_path is None


async def test_uploaded_avatar_wins_over_provider(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User, teacher_token: dict
) -> None:
    teacher_user.avatar_external_url = "https://avatars.yandex.net/get-yapic/abc/islands-200"
    await db_session.commit()

    resp = await client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("me.png", _png(), "image/png")},
        cookies=teacher_token,
    )
    assert "/files/avatars/" in resp.json()["avatar_url"]


async def test_avatar_url_resolves_for_anonymous_visitor(
    client: AsyncClient, db_session: AsyncSession, teacher_user: User, teacher_token: dict
) -> None:
    """An avatar is a public resource even on a hidden profile (DECISIONS §59):
    the signed URL carries the owner's uid, which is only part of the HMAC and
    not an access check."""
    # The fixture builds the row directly, so it carries the column default
    # rather than the role default register() would apply.
    teacher_user.profile_visibility = ProfileVisibility.public
    await db_session.commit()

    await client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("me.png", _png(), "image/png")},
        cookies=teacher_token,
    )
    # Anonymous read of the profile still yields a usable avatar URL...
    body = (await client.get(_profile_url(teacher_user))).json()
    assert body["avatar_url"]

    # ...and that URL's signature verifies. The uid it carries is the profile
    # owner's, NOT the requester's, which is exactly why an anonymous visitor
    # can load it. (Asserting the signature rather than GETting the bytes: the
    # /files route reads settings.STORAGE_PATH directly, while the test harness
    # only redirects storage_service.)
    parsed = urlparse(body["avatar_url"])
    query = parse_qs(parsed.query)
    assert query["uid"] == [str(teacher_user.id)]
    assert verify_signed_url(
        unquote(parsed.path.split("/files/", 1)[1]),
        query["uid"][0],
        int(query["expires"][0]),
        query["sig"][0],
    )
