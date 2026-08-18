"""Unit tests for lesson_material_service policy helpers.

Covers the parts that decide whether an upload is allowed at all — the
extension/MIME whitelist and the "which limit did you blow" branch — plus the
schema length caps. Route-level authorization (owner vs enrolled student vs
draft lesson) is covered in tests/integration/test_lesson_materials_routes.py.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.constants import (
    LESSON_MATERIAL_CATEGORY_MAX_SIZE_MB,
    LESSON_NOTE_MAX_CONTENT_CHARS,
)
from app.schemas.lesson_material import MaterialUpdate, NoteCreate, NoteUpdate
from app.services import lesson_material_service as svc

pytestmark = pytest.mark.unit


def _file(filename: str, content_type: str | None = None, size: int | None = None) -> object:
    """Minimal UploadFile stand-in: the resolver only reads these attributes."""
    return SimpleNamespace(filename=filename, content_type=content_type, size=size)


# ── Whitelist ────────────────────────────────────────────────────────────────


def test_resolve_category_uses_mime_when_allowed() -> None:
    category, ext = svc._resolve_category(_file("handout.pdf", "application/pdf"))
    assert (category, ext) == ("document", "pdf")


def test_resolve_category_falls_back_to_extension_when_mime_missing() -> None:
    category, ext = svc._resolve_category(_file("clip.mp4", None))
    assert (category, ext) == ("video", "mp4")


def test_resolve_category_rejects_extension_off_whitelist() -> None:
    with pytest.raises(HTTPException) as exc:
        svc._resolve_category(_file("payload.exe", "application/pdf"))
    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "extension_not_allowed"


def test_resolve_category_rejects_forged_mime_on_disallowed_extension() -> None:
    # A whitelisted Content-Type must not smuggle a disallowed extension through.
    with pytest.raises(HTTPException) as exc:
        svc._resolve_category(_file("script.sh", "image/png"))
    assert exc.value.detail["code"] == "extension_not_allowed"


def test_every_whitelisted_extension_resolves_to_a_known_category() -> None:
    from app.constants import LESSON_MATERIAL_EXTENSION_MIME

    for ext in LESSON_MATERIAL_EXTENSION_MIME:
        category, resolved_ext = svc._resolve_category(_file(f"x.{ext}", None))
        assert resolved_ext == ext
        assert category in LESSON_MATERIAL_CATEGORY_MAX_SIZE_MB


# ── Limit errors ─────────────────────────────────────────────────────────────


def test_too_large_reports_per_file_limit() -> None:
    exc = svc._too_large("big.pdf", "document", 100 * 1024 * 1024, over_total=False)
    assert exc.status_code == 400
    assert exc.detail["code"] == "file_too_large"
    assert exc.detail["max_file_mb"] == 100


def test_too_large_reports_lesson_total_limit() -> None:
    exc = svc._too_large("big.pdf", "document", 100 * 1024 * 1024, over_total=True)
    assert exc.detail["code"] == "materials_too_large"
    assert "max_total_mb" in exc.detail


def test_material_prefix_is_lesson_scoped() -> None:
    lesson_id = uuid4()
    # Purge deletes this exact prefix — it must stay per-lesson and non-root.
    prefix = svc.material_prefix(lesson_id)
    assert prefix == f"materials/{lesson_id}"
    assert "/" in prefix and len(prefix) > 3


def test_limits_payload_lists_allowed_extensions() -> None:
    limits = svc._limits()
    assert "pdf" in limits.allowed_ext
    assert "exe" not in limits.allowed_ext
    assert limits.note_max_chars == LESSON_NOTE_MAX_CONTENT_CHARS


# ── Schema caps ──────────────────────────────────────────────────────────────


def test_note_create_strips_and_rejects_blank() -> None:
    assert NoteCreate(title="  T  ", content="  body  ").title == "T"
    with pytest.raises(ValidationError):
        NoteCreate(title="   ", content="body")


def test_note_content_is_capped() -> None:
    NoteCreate(title="ok", content="x" * LESSON_NOTE_MAX_CONTENT_CHARS)
    with pytest.raises(ValidationError):
        NoteCreate(title="ok", content="x" * (LESSON_NOTE_MAX_CONTENT_CHARS + 1))


def test_note_update_allows_partial_payload() -> None:
    assert NoteUpdate(title="only title").model_dump(exclude_unset=True) == {"title": "only title"}


def test_material_update_blank_description_becomes_null() -> None:
    assert MaterialUpdate(description="   ").description is None


# ── Download URLs: local (HMAC) vs S3 (presigned) ────────────────────────────


def _material() -> object:
    now = datetime(2026, 8, 19, 12, 0, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=uuid4(),
        lesson_id=uuid4(),
        title="Методичка",
        description=None,
        file_path="materials/abc/handout.pdf",
        original_filename="handout.pdf",
        content_type="application/pdf",
        size_bytes=1234,
        uploaded_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


def test_serialize_material_signs_local_urls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.storage_service import StorageService

    monkeypatch.setattr(
        svc,
        "storage_service",
        StorageService(base_path=str(tmp_path), base_url="http://localhost:8000"),
    )

    url = svc.serialize_material(_material(), "viewer-1").download_url

    assert url.startswith("http://localhost:8000/files/")
    assert "materials/abc/handout.pdf" in unquote(url)
    # Local delivery is HMAC-signed and time-boxed — never a bare path.
    assert "sig=" in url and "expires=" in url


def test_serialize_material_uses_presigned_url_on_s3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """S3 has no HMAC layer: StorageService must hand the object's presigned
    URL through untouched (the same branch the prod backend takes)."""
    from app.services.storage_service import StorageService

    class _FakeS3Backend:
        def get_url(self, relative_path: str) -> str:
            return f"https://s3.example.com/bucket/{relative_path}?X-Amz-Signature=deadbeef"

    service = StorageService(base_path=str(tmp_path), base_url="http://localhost:8000")
    service._backend = _FakeS3Backend()
    monkeypatch.setattr(svc, "storage_service", service)

    url = svc.serialize_material(_material(), "viewer-1").download_url

    assert url == (
        "https://s3.example.com/bucket/materials/abc/handout.pdf?X-Amz-Signature=deadbeef"
    )
    assert "sig=" not in url
