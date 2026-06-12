"""Unit tests for app.services.storage_service.StorageService."""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Any

import pytest
from fastapi import UploadFile

from app.services.storage_service import StorageService

pytestmark = pytest.mark.unit


def _upload_file(name: str, content: bytes) -> UploadFile:
    return UploadFile(filename=name, file=io.BytesIO(content))


async def test_save_upload_writes_file_and_returns_relative_path(tmp_path: Path) -> None:
    svc = StorageService(base_path=str(tmp_path), base_url="http://t.example")

    rel = await svc.save_upload(_upload_file("hello.txt", b"hello world"), "uploads")

    assert rel.startswith("uploads/")
    assert rel.endswith("_hello.txt")
    full = tmp_path / rel
    assert full.exists()
    assert full.read_bytes() == b"hello world"


async def test_save_upload_normalises_dangerous_filename(tmp_path: Path) -> None:
    svc = StorageService(base_path=str(tmp_path), base_url="http://t.example")
    rel = await svc.save_upload(_upload_file("a/b\\c.txt", b"x"), "subdir")
    # Slashes/backslashes in original filename are replaced before joining.
    assert "/" not in rel.split("/", 1)[1].split("_", 1)[1]


async def test_save_upload_bounded_writes_within_limit(tmp_path: Path) -> None:
    svc = StorageService(base_path=str(tmp_path), base_url="http://t.example")
    rel, size = await svc.save_upload_bounded(_upload_file("a.txt", b"abcde"), "sub", 10)
    assert size == 5
    assert (tmp_path / rel).read_bytes() == b"abcde"


async def test_save_upload_bounded_allows_exact_boundary(tmp_path: Path) -> None:
    svc = StorageService(base_path=str(tmp_path), base_url="http://t.example")
    # size == cap passes; size > cap aborts.
    rel, size = await svc.save_upload_bounded(_upload_file("a.bin", b"x" * 8), "sub", 8)
    assert size == 8
    assert (tmp_path / rel).exists()


async def test_save_upload_bounded_aborts_midstream_and_removes_partial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import storage_service as ss

    # Tiny chunk so a small payload exercises the multi-chunk streaming abort.
    monkeypatch.setattr(ss, "_UPLOAD_CHUNK_BYTES", 4)
    svc = StorageService(base_path=str(tmp_path), base_url="http://t.example")

    with pytest.raises(ss.UploadTooLargeError):
        await svc.save_upload_bounded(_upload_file("big.bin", b"x" * 50), "sub", 10)

    # The whole file was never written and the partial was unlinked.
    sub = tmp_path / "sub"
    assert not sub.exists() or not any(sub.iterdir())


def test_get_url_starts_with_base_url_and_contains_path(tmp_path: Path) -> None:
    svc = StorageService(base_path=str(tmp_path), base_url="http://t.example/")
    url = svc.get_url("uploads/x.png", user_id="user-1")
    assert url.startswith("http://t.example/files/uploads/x.png?")
    assert "uid=user-1" in url
    assert "sig=" in url
    assert "expires=" in url


def test_delete_file_is_idempotent(tmp_path: Path) -> None:
    svc = StorageService(base_path=str(tmp_path), base_url="http://t.example")
    target = tmp_path / "victim.txt"
    target.write_text("bye")
    assert target.exists()
    svc.delete_file("victim.txt")
    assert not target.exists()
    # Second call must not raise.
    svc.delete_file("victim.txt")


def test_resign_url_replaces_signature_for_new_user(tmp_path: Path) -> None:
    svc = StorageService(base_path=str(tmp_path), base_url="http://t.example")
    original = svc.get_url("a/b.png", user_id="u1")
    resigned = svc.resign_url(original, user_id="u2")
    assert resigned is not None
    assert "uid=u2" in resigned
    assert "uid=u1" not in resigned


def test_resign_url_returns_none_for_none() -> None:
    svc = StorageService(base_path="/tmp", base_url="http://t.example")
    assert svc.resign_url(None, user_id="u1") is None
