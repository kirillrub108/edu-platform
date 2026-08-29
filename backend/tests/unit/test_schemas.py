"""Unit tests for Pydantic schemas — validators, enums, edge cases."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.auth import ChangePasswordRequest, UserRegister
from app.schemas.course import CourseCreate
from app.schemas.lesson import (
    LessonCreate,
    ScriptUpdateRequest,
    VideoGenerateRequest,
)
from app.schemas.slide import SlideTextUpdate

pytestmark = pytest.mark.unit


# ── VideoGenerateRequest ────────────────────────────────────────────────────


@pytest.mark.parametrize("voice", ["nova", "shimmer", "coral", "alloy", "onyx", "echo"])
def test_video_generate_request_accepts_valid_voices(voice: str) -> None:
    req = VideoGenerateRequest(voice=voice)
    assert req.voice == voice


def test_video_generate_request_defaults_to_nova() -> None:
    assert VideoGenerateRequest().voice == "nova"


@pytest.mark.parametrize("voice", ["bad", "", "NOVA", "xenia", "ballad", "verse"])
def test_video_generate_request_rejects_invalid_voice(voice: str) -> None:
    with pytest.raises(ValidationError):
        VideoGenerateRequest(voice=voice)


# ── UserRegister ────────────────────────────────────────────────────────────

CONSENTS = {"accepted_privacy": True, "accepted_terms": True}


def test_user_register_accepts_teacher_role() -> None:
    u = UserRegister(email="x@y.com", password="password123", role="teacher", **CONSENTS)
    assert u.role.value == "teacher"


def test_user_register_accepts_student_role() -> None:
    u = UserRegister(email="x@y.com", password="password123", role="student", **CONSENTS)
    assert u.role.value == "student"


def test_user_register_rejects_unknown_role() -> None:
    with pytest.raises(ValidationError):
        UserRegister(email="x@y.com", password="password123", role="admin", **CONSENTS)


@pytest.mark.parametrize("password", ["short", "1234567", ""])
def test_user_register_rejects_short_password(password: str) -> None:
    with pytest.raises(ValidationError):
        UserRegister(email="x@y.com", password=password, **CONSENTS)


@pytest.mark.parametrize(
    "email",
    ["x@mailinator.com", "X@MAILINATOR.COM", "x@sub.mailinator.com", "x@yopmail.com"],
)
def test_user_register_rejects_disposable_email(email: str) -> None:
    with pytest.raises(ValidationError, match="disposable_email_not_allowed"):
        UserRegister(email=email, password="password123", **CONSENTS)


@pytest.mark.parametrize(
    "email",
    ["x@gmail.com", "x@yandex.ru", "x@mail.ru", "x@outlook.com"],
)
def test_user_register_accepts_legitimate_email(email: str) -> None:
    u = UserRegister(email=email, password="password123", **CONSENTS)
    assert u.email == email


def test_user_register_accepts_full_name_at_column_limit() -> None:
    u = UserRegister(email="x@y.com", password="password123", full_name="a" * 255, **CONSENTS)
    assert len(u.full_name) == 255


def test_user_register_rejects_full_name_over_column_limit() -> None:
    """User.full_name is String(255) — over the limit must be a 422, not a
    500 from a truncated INSERT."""
    with pytest.raises(ValidationError):
        UserRegister(email="x@y.com", password="password123", full_name="a" * 256, **CONSENTS)


@pytest.mark.parametrize("password", ["        ", "\t\n\t\n\t\n\t\n"])
def test_user_register_rejects_whitespace_only_password(password: str) -> None:
    # Both cases are >= min_length=8 raw chars, so this exercises the blank
    # check itself rather than the length constraint firing first.
    with pytest.raises(ValidationError, match="password_blank"):
        UserRegister(email="x@y.com", password=password, **CONSENTS)


def test_user_register_accepts_password_with_meaningful_spaces() -> None:
    """Only whitespace-only passwords are rejected — spaces inside a real
    password are untouched (not trimmed, not rejected)."""
    u = UserRegister(email="x@y.com", password=" pass word ", **CONSENTS)
    assert u.password == " pass word "


def test_change_password_rejects_whitespace_only_new_password() -> None:
    """The blank-password rule lives on the shared PasswordStr, so it also
    covers ChangePasswordRequest.new_password without a second validator."""
    with pytest.raises(ValidationError, match="password_blank"):
        ChangePasswordRequest(old_password="whatever", new_password="        ")


# ── CourseCreate ────────────────────────────────────────────────────────────


def test_course_create_requires_title() -> None:
    with pytest.raises(ValidationError):
        CourseCreate(description="no title")  # type: ignore[call-arg]


def test_course_create_rejects_empty_title() -> None:
    with pytest.raises(ValidationError):
        CourseCreate(title="")


# ── LessonCreate ────────────────────────────────────────────────────────────


def test_lesson_create_defaults() -> None:
    lesson = LessonCreate(title="L", module_id=uuid4())
    assert lesson.content_type.value == "video"
    assert lesson.order == 0


# ── SlideTextUpdate ─────────────────────────────────────────────────────────


def test_slide_text_update_accepts_empty_string() -> None:
    """Schema currently has no min_length constraint on edited_text — "" is
    a valid update value (lets a teacher clear their edits)."""
    s = SlideTextUpdate(edited_text="")
    assert s.edited_text == ""


def test_slide_text_update_requires_field() -> None:
    with pytest.raises(ValidationError):
        SlideTextUpdate()  # type: ignore[call-arg]


# ── ScriptUpdateRequest ─────────────────────────────────────────────────────


def test_script_update_accepts_long_text() -> None:
    text = "x" * 100_000
    assert ScriptUpdateRequest(script=text).script == text
