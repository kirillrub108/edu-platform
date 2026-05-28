"""Unit-style tests for comment_service helpers and the CommentRead.is_edited
derivation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.user import UserRole
from app.schemas.comment import (
    CommentAuthor,
    CommentCreate,
    CommentRead,
    CommentUpdate,
)


def _author() -> CommentAuthor:
    return CommentAuthor(id=uuid4(), full_name="A", role=UserRole.student)


def test_is_edited_false_when_timestamps_equal() -> None:
    now = datetime.now(timezone.utc)
    c = CommentRead(
        id=uuid4(),
        lesson_id=uuid4(),
        content="x",
        author=_author(),
        created_at=now,
        updated_at=now,
    )
    assert c.is_edited is False


def test_is_edited_true_when_updated_after_created() -> None:
    now = datetime.now(timezone.utc)
    c = CommentRead(
        id=uuid4(),
        lesson_id=uuid4(),
        content="x",
        author=_author(),
        created_at=now,
        updated_at=now + timedelta(milliseconds=1),
    )
    assert c.is_edited is True


def test_comment_create_strips_whitespace() -> None:
    assert CommentCreate(content="  hi  ").content == "hi"


def test_comment_create_empty_after_strip_rejected() -> None:
    # Pydantic raises ValidationError (subclass of ValueError) when the
    # post-strip value fails the min_length=1 constraint.
    with pytest.raises(ValueError):
        CommentCreate(content="   ")


def test_comment_create_truly_empty_rejected() -> None:
    with pytest.raises(ValueError):
        CommentCreate(content="")


def test_comment_update_strips_whitespace() -> None:
    assert CommentUpdate(content="  edited  ").content == "edited"


def test_comment_create_max_length_enforced() -> None:
    with pytest.raises(ValueError):
        CommentCreate(content="x" * 2001)
