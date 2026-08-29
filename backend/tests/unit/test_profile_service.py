"""Pure parts of profile_service: the privacy rule, provider avatar claims, and
the image normalization that strips EXIF."""

import uuid
from io import BytesIO

import pytest
from PIL import Image

from app.constants import AVATAR_SIZE_PX
from app.models.user import ProfileVisibility, User, UserRole
from app.services.profile_service import (
    _visibility_allows,
    apply_provider_avatar,
    normalize_avatar,
    profile_defaults_for_role,
    provider_avatar_url,
)

pytestmark = pytest.mark.unit


# ── privacy rule ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("visibility", "is_owner", "is_authenticated", "is_enrolling_teacher", "expected"),
    [
        # The owner always gets through, whatever the setting.
        (ProfileVisibility.private, True, True, False, True),
        (ProfileVisibility.public, True, True, False, True),
        # public: anonymous included.
        (ProfileVisibility.public, False, False, False, True),
        (ProfileVisibility.public, False, True, False, True),
        # authenticated: signed in only.
        (ProfileVisibility.authenticated, False, False, False, False),
        (ProfileVisibility.authenticated, False, True, False, True),
        # private: only a teacher who actually teaches this student.
        (ProfileVisibility.private, False, False, False, False),
        (ProfileVisibility.private, False, True, False, False),
        (ProfileVisibility.private, False, True, True, True),
    ],
)
def test_visibility_rule(
    visibility: ProfileVisibility,
    is_owner: bool,
    is_authenticated: bool,
    is_enrolling_teacher: bool,
    expected: bool,
) -> None:
    assert (
        _visibility_allows(
            visibility,
            is_owner=is_owner,
            is_authenticated=is_authenticated,
            is_enrolling_teacher=is_enrolling_teacher,
        )
        is expected
    )


def test_role_defaults_differ() -> None:
    teacher_vis, teacher_stats = profile_defaults_for_role(UserRole.teacher)
    student_vis, student_stats = profile_defaults_for_role(UserRole.student)
    assert (teacher_vis, teacher_stats) == (ProfileVisibility.public, True)
    assert (student_vis, student_stats) == (ProfileVisibility.authenticated, False)


# ── provider avatars ─────────────────────────────────────────────────────────


def test_google_picture_claim() -> None:
    url = provider_avatar_url("google", {"picture": "https://lh3.googleusercontent.com/a/abc=s96"})
    assert url == "https://lh3.googleusercontent.com/a/abc=s96"


def test_google_missing_picture() -> None:
    assert provider_avatar_url("google", {"sub": "1", "email": "a@b.c"}) is None


def test_yandex_builds_url_from_avatar_id() -> None:
    url = provider_avatar_url("yandex", {"default_avatar_id": "42xyz"})
    assert url == "https://avatars.yandex.net/get-yapic/42xyz/islands-200"


def test_yandex_respects_is_avatar_empty() -> None:
    """The flag exists precisely so we do not show the default grey silhouette."""
    assert (
        provider_avatar_url("yandex", {"default_avatar_id": "42xyz", "is_avatar_empty": True})
        is None
    )


def test_yandex_without_avatar_id() -> None:
    assert provider_avatar_url("yandex", {"login": "someone"}) is None


@pytest.mark.parametrize(
    "picture",
    [
        "https://evil.example.com/pic.png",  # off-allowlist host
        "http://lh3.googleusercontent.com/a/abc",  # allowlisted host, but plain http
        "javascript:alert(1)",
        "",
        None,
        12345,
    ],
)
def test_off_allowlist_urls_rejected(picture: object) -> None:
    assert provider_avatar_url("google", {"picture": picture}) is None


def test_unknown_provider_is_none() -> None:
    claims = {"picture": "https://lh3.googleusercontent.com/x"}
    assert provider_avatar_url("facebook", claims) is None


def test_apply_provider_avatar_overwrites_and_clears() -> None:
    user = User(id=uuid.uuid4(), email="a@b.c", role=UserRole.student)
    apply_provider_avatar(user, "google", {"picture": "https://lh3.googleusercontent.com/a/one"})
    assert user.avatar_external_url == "https://lh3.googleusercontent.com/a/one"

    # Re-login after the picture changed on the provider's side.
    apply_provider_avatar(user, "google", {"picture": "https://lh3.googleusercontent.com/a/two"})
    assert user.avatar_external_url == "https://lh3.googleusercontent.com/a/two"

    # Provider stopped offering one — clearing is intentional, not a miss.
    apply_provider_avatar(user, "google", {})
    assert user.avatar_external_url is None


# ── image normalization ──────────────────────────────────────────────────────


def _jpeg_with_exif(width: int = 800, height: int = 400) -> bytes:
    """A JPEG carrying an EXIF block, including the GPS-adjacent tags that make
    stripping a privacy requirement rather than a nicety."""
    img = Image.new("RGB", (width, height), (120, 30, 200))
    exif = img.getexif()
    exif[0x010F] = "TestCam"  # Make
    exif[0x0110] = "Model X"  # Model
    exif[0x0112] = 1  # Orientation
    buf = BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    return buf.getvalue()


def test_normalize_strips_exif() -> None:
    source = _jpeg_with_exif()
    assert Image.open(BytesIO(source)).getexif(), "fixture must actually carry EXIF"

    with Image.open(BytesIO(normalize_avatar(source))) as out:
        assert dict(out.getexif()) == {}


def test_normalize_center_crops_to_square() -> None:
    with Image.open(BytesIO(normalize_avatar(_jpeg_with_exif(900, 300)))) as out:
        assert out.size == (AVATAR_SIZE_PX, AVATAR_SIZE_PX)
        assert out.format == "WEBP"


def test_normalize_accepts_rgba_png() -> None:
    """Transparency is flattened rather than rejected — an RGBA PNG is the most
    common avatar upload after a phone photo."""
    img = Image.new("RGBA", (300, 300), (10, 200, 100, 128))
    buf = BytesIO()
    img.save(buf, format="PNG")

    with Image.open(BytesIO(normalize_avatar(buf.getvalue()))) as out:
        assert out.size == (AVATAR_SIZE_PX, AVATAR_SIZE_PX)


def test_normalize_rejects_garbage() -> None:
    with pytest.raises(OSError):
        normalize_avatar(b"not an image at all")
