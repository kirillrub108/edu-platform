"""Unit tests for app.services.file_validation_service.

This is the only gate between an uploaded file and the storage volume: a wrong
verdict here means a disguised executable is stored, a zip-slip entry escapes
the extraction root, or a legitimate lecture is rejected. Everything is
in-memory — no storage backend is touched.
"""

from __future__ import annotations

import zipfile
from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app.services import file_validation_service as fvs
from app.services.file_validation_service import validate_upload

pytestmark = pytest.mark.unit

_PDF = b"%PDF-1.4\n" + b"0" * 64
_ZIP_MAGIC = b"PK\x03\x04"
_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def _upload(filename: str, content: bytes, size: int | None = None) -> UploadFile:
    return UploadFile(
        file=BytesIO(content), filename=filename, size=size if size is not None else len(content)
    )


def _zip_bytes(names: list[str], payload: bytes = b"x") -> bytes:
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in names:
            zf.writestr(name, payload)
    return buf.getvalue()


# ── filename / extension ──────────────────────────────────────────────────────


async def test_missing_filename_is_rejected() -> None:
    with pytest.raises(HTTPException, match="Filename is required"):
        await validate_upload(_upload("", _PDF), [".pdf"])


@pytest.mark.parametrize("name", ["../../etc/passwd.pdf", "dir\\lecture.pdf"])
async def test_path_separators_in_filename_are_rejected(name: str) -> None:
    with pytest.raises(HTTPException, match="Invalid filename"):
        await validate_upload(_upload(name, _PDF), [".pdf"])


async def test_extension_outside_the_whitelist_is_rejected() -> None:
    with pytest.raises(HTTPException, match="not allowed"):
        await validate_upload(_upload("payload.exe", _PDF), [".pdf"])


@pytest.mark.parametrize("name", ["malware.exe.pdf", "shell.php.pdf", "script.ps1.pdf"])
async def test_double_extension_trap(name: str) -> None:
    with pytest.raises(HTTPException, match="multiple extensions"):
        await validate_upload(_upload(name, _PDF), [".pdf"])


async def test_version_markers_in_the_name_are_allowed() -> None:
    """"report.v1.2.pdf" is a legitimate name, not a double-extension trick."""
    await validate_upload(_upload("report.v1.2.pdf", _PDF), [".pdf"])


# ── magic bytes ───────────────────────────────────────────────────────────────


async def test_pdf_extension_requires_pdf_header() -> None:
    with pytest.raises(HTTPException, match="does not match .pdf"):
        await validate_upload(_upload("fake.pdf", b"MZ\x90\x00 this is a PE binary"), [".pdf"])


async def test_pptx_extension_requires_zip_header() -> None:
    with pytest.raises(HTTPException, match="does not match .pptx"):
        await validate_upload(_upload("fake.pptx", b"not a zip at all"), [".pptx"])


async def test_legacy_ppt_requires_ole_header() -> None:
    await validate_upload(_upload("deck.ppt", _OLE + b"rest"), [".ppt"])

    with pytest.raises(HTTPException, match="does not match .ppt"):
        await validate_upload(_upload("deck.ppt", _ZIP_MAGIC + b"rest"), [".ppt"])


async def test_mp4_requires_ftyp_box() -> None:
    await validate_upload(_upload("clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"0" * 32), [".mp4"])

    with pytest.raises(HTTPException, match="does not match .mp4"):
        await validate_upload(_upload("clip.mp4", b"\x00" * 64), [".mp4"])


@pytest.mark.parametrize("encoding", ["utf-8", "cp1251"])
async def test_text_formats_accept_common_encodings(encoding: str) -> None:
    await validate_upload(_upload("script.txt", "Лекция по физике".encode(encoding)), [".txt"])


async def test_text_formats_accept_any_bytes_via_the_latin1_fallback() -> None:
    """Known gap, pinned deliberately: latin-1 decodes every byte sequence, so
    the text branch of _check_magic cannot reject a renamed binary. Dropping
    latin-1 from the fallback list must be a conscious decision, not a slip."""
    await validate_upload(_upload("script.txt", b"\xff\xfe\x00\xd8\x00\x00"), [".txt"])


# ── ZIP integrity ─────────────────────────────────────────────────────────────


async def test_valid_pptx_archive_passes() -> None:
    await validate_upload(_upload("deck.pptx", _zip_bytes(["ppt/presentation.xml"])), [".pptx"])


async def test_corrupted_archive_is_rejected() -> None:
    with pytest.raises(HTTPException, match="Corrupted or invalid archive"):
        await validate_upload(_upload("deck.pptx", _ZIP_MAGIC + b"garbage" * 8), [".pptx"])


@pytest.mark.parametrize("entry", ["../escape.xml", "/absolute.xml", "a/../../escape.xml"])
async def test_zip_slip_entries_are_rejected(entry: str) -> None:
    with pytest.raises(HTTPException, match="Archive entry path is invalid"):
        await validate_upload(_upload("deck.pptx", _zip_bytes([entry])), [".pptx"])


async def test_backslash_entry_paths_are_normalized_before_the_check() -> None:
    with pytest.raises(HTTPException, match="Archive entry path is invalid"):
        await validate_upload(_upload("deck.pptx", _zip_bytes(["a\\..\\..\\escape.xml"])), [".pptx"])


async def test_too_many_archive_entries_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(fvs, "_MAX_ZIP_ENTRIES", 2)

    with pytest.raises(HTTPException, match="too many entries"):
        await validate_upload(_upload("deck.pptx", _zip_bytes(["a", "b", "c"])), [".pptx"])


async def test_zip_bomb_uncompressed_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """The compressed upload is tiny; the cap is on the inflated total."""
    monkeypatch.setattr(fvs, "_MAX_ZIP_UNCOMPRESSED", 1024)
    content = _zip_bytes(["big.xml"], payload=b"0" * 4096)

    with pytest.raises(HTTPException, match="uncompressed size exceeds"):
        await validate_upload(_upload("deck.pptx", content), [".pptx"])


# ── size limits + stream position ─────────────────────────────────────────────


async def test_oversized_upload_is_rejected_by_extension_limit() -> None:
    oversized = fvs.SIZE_LIMITS[".pdf"] + 1

    with pytest.raises(HTTPException, match="File too large"):
        await validate_upload(_upload("lecture.pdf", _PDF, size=oversized), [".pdf"])


async def test_size_limits_can_be_delegated_to_the_caller() -> None:
    """Assignment attachments apply their own per-category caps, but must still
    go through the magic-byte check."""
    oversized = fvs.SIZE_LIMITS[".pdf"] + 1

    await validate_upload(
        _upload("lecture.pdf", _PDF, size=oversized), [".pdf"], enforce_size_limits=False
    )

    with pytest.raises(HTTPException, match="does not match"):
        await validate_upload(
            _upload("lecture.pdf", b"MZ binary", size=oversized),
            [".pdf"],
            enforce_size_limits=False,
        )


async def test_unknown_size_is_not_treated_as_oversized() -> None:
    await validate_upload(_upload("lecture.pdf", _PDF, size=None), [".pdf"])


async def test_file_pointer_is_rewound_for_the_caller() -> None:
    """The router streams the file right after validation — a non-zero offset
    would silently truncate the stored document."""
    content = _zip_bytes(["ppt/presentation.xml"])
    upload = _upload("deck.pptx", content)

    await validate_upload(upload, [".pptx"])

    assert await upload.read() == content
