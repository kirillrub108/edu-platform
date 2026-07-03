"""Unit tests for Pydantic schemas — validators, enums, edge cases."""

from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.schemas.auth import UserRegister
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


# ── CourseCreate ────────────────────────────────────────────────────────────

def test_course_create_requires_title() -> None:
    with pytest.raises(ValidationError):
        CourseCreate(description="no title")  # type: ignore[call-arg]


def test_course_create_rejects_empty_title() -> None:
    with pytest.raises(ValidationError):
        CourseCreate(title="")


# ── LessonCreate ────────────────────────────────────────────────────────────

def test_lesson_create_defaults() -> None:
    l = LessonCreate(title="L", module_id=uuid4())
    assert l.content_type.value == "video"
    assert l.order == 0
    assert l.creation_mode.value == "presentation_and_text"


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
