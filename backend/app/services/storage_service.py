import asyncio
import io
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote, urlparse

import structlog
from fastapi import UploadFile

from app.config import settings
from app.services.signed_url_service import generate_signed_url

logger = structlog.get_logger()


# Streaming granularity for bounded uploads (1 MiB).
_UPLOAD_CHUNK_BYTES = 1024 * 1024


class UploadTooLargeError(Exception):
    """Raised by save_upload_bounded when an upload streams past its byte cap.
    Any partially written object is removed before this propagates, so callers
    only need to translate it into a user-facing error."""

    def __init__(self, limit_bytes: int) -> None:
        self.limit_bytes = limit_bytes
        super().__init__(f"upload exceeded {limit_bytes} bytes")


class StorageBackend(Protocol):
    def save(self, relative_path: str, data: bytes) -> str: ...
    def get_url(self, relative_path: str) -> str: ...
    def get_full_path(self, relative_path: str) -> str: ...
    def delete(self, relative_path: str) -> None: ...
    def exists(self, relative_path: str) -> bool: ...
    def download_to(self, relative_path: str, dest_path: str) -> None: ...
    def upload_from(self, relative_path: str, src_path: str) -> str: ...
    def list_prefix(self, prefix: str) -> list[str]: ...


class LocalBackend:
    def __init__(self, base_path: str, base_url: str) -> None:
        self.base_path = Path(base_path)
        self.base_url = base_url.rstrip("/")
        self.base_path.mkdir(parents=True, exist_ok=True)

    def save(self, relative_path: str, data: bytes) -> str:
        full = self.base_path / relative_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_bytes(data)
        return relative_path

    def get_url(self, relative_path: str) -> str:
        return f"{self.base_url}/files/{relative_path}"

    def get_full_path(self, relative_path: str) -> str:
        return str(self.base_path / relative_path)

    def delete(self, relative_path: str) -> None:
        full = self.base_path / relative_path
        if full.exists():
            full.unlink()

    def exists(self, relative_path: str) -> bool:
        return (self.base_path / relative_path).exists()

    def download_to(self, relative_path: str, dest_path: str) -> None:
        shutil.copy2(self.base_path / relative_path, dest_path)

    def upload_from(self, relative_path: str, src_path: str) -> str:
        full = self.base_path / relative_path
        full.parent.mkdir(parents=True, exist_ok=True)
        if Path(src_path).resolve() != full.resolve():
            shutil.copy2(src_path, full)
        return relative_path

    def list_prefix(self, prefix: str) -> list[str]:
        root = self.base_path / prefix
        if not root.exists():
            return []
        if root.is_file():
            return [prefix]
        return [
            str(p.relative_to(self.base_path)).replace("\\", "/")
            for p in root.rglob("*")
            if p.is_file()
        ]


class S3Backend:
    def __init__(self) -> None:
        import boto3

        self._client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL,
            aws_access_key_id=settings.S3_ACCESS_KEY_ID,
            aws_secret_access_key=settings.S3_SECRET_ACCESS_KEY,
            region_name=settings.S3_REGION,
        )
        self._bucket = settings.S3_BUCKET_NAME
        self._expire = settings.S3_PRESIGNED_URL_EXPIRE_SECONDS

    def save(self, relative_path: str, data: bytes) -> str:
        self._client.upload_fileobj(io.BytesIO(data), self._bucket, relative_path)
        return relative_path

    def get_url(self, relative_path: str) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": relative_path},
            ExpiresIn=self._expire,
        )

    def get_presigned_url(self, relative_path: str, ttl_seconds: int) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": relative_path},
            ExpiresIn=ttl_seconds,
        )

    def get_full_path(self, relative_path: str) -> str:
        raise NotImplementedError("S3Backend has no local path — use get_url() instead")

    def delete(self, relative_path: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=relative_path)

    def exists(self, relative_path: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(Bucket=self._bucket, Key=relative_path)
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("404", "NoSuchKey"):
                return False
            raise

    def download_to(self, relative_path: str, dest_path: str) -> None:
        """Stream an object to a local file — never buffers the whole body."""
        self._client.download_file(self._bucket, relative_path, dest_path)

    def upload_from(self, relative_path: str, src_path: str) -> str:
        """Stream a local file into the bucket (multipart handled by boto3)."""
        self._client.upload_file(src_path, self._bucket, relative_path)
        return relative_path

    def list_prefix(self, prefix: str) -> list[str]:
        """All keys under a prefix. Paginated: a page caps at 1000 keys, and
        without this loop a purge would silently skip everything past it."""
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys


_backend_instance: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    global _backend_instance
    if _backend_instance is None:
        if settings.STORAGE_BACKEND == "s3":
            if not settings.S3_BUCKET_NAME:
                raise ValueError("S3_BUCKET_NAME must be set when STORAGE_BACKEND=s3")
            _backend_instance = S3Backend()
        else:
            # Signed /files/* links point at the public files host (nginx/CDN
            # domain) in prod; fall back to BASE_URL in dev.
            files_base_url = settings.PUBLIC_FILES_BASE_URL or settings.BASE_URL
            _backend_instance = LocalBackend(settings.STORAGE_PATH, files_base_url)
    return _backend_instance


class StorageService:
    def __init__(self, base_path: str | None = None, base_url: str | None = None) -> None:
        if base_path is not None or base_url is not None:
            # Direct construction path — used in tests to inject a temp directory.
            self._backend: StorageBackend = LocalBackend(
                base_path or settings.STORAGE_PATH,
                base_url or settings.BASE_URL,
            )
        else:
            self._backend = get_storage_backend()

    async def save_upload(self, file: UploadFile, subfolder: str) -> str:
        safe_name = (file.filename or "file").replace("/", "_").replace("\\", "_")
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        relative = os.path.join(subfolder, unique_name).replace("\\", "/")
        data = await file.read()
        await asyncio.to_thread(self._backend.save, relative, data)
        return relative

    async def save_upload_bounded(
        self, file: UploadFile, subfolder: str, max_bytes: int
    ) -> tuple[str, int]:
        """Stream an upload into storage, hard-aborting the moment the written
        size exceeds max_bytes. On overflow the partial object is removed and
        UploadTooLargeError is raised. Returns (relative_path, bytes_written).

        Local storage streams to disk at O(chunk) memory; the (optional) S3
        backend buffers up to the cap since its save() takes a full byte string.
        """
        safe_name = (file.filename or "file").replace("/", "_").replace("\\", "_")
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        relative = os.path.join(subfolder, unique_name).replace("\\", "/")
        if isinstance(self._backend, LocalBackend):
            return await self._stream_to_local(file, relative, max_bytes)
        return await self._buffer_bounded(file, relative, max_bytes)

    async def _stream_to_local(
        self, file: UploadFile, relative: str, max_bytes: int
    ) -> tuple[str, int]:
        full = Path(self._backend.get_full_path(relative))
        await asyncio.to_thread(full.parent.mkdir, parents=True, exist_ok=True)
        handle = await asyncio.to_thread(open, full, "wb")
        total = 0
        try:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    await asyncio.to_thread(handle.close)
                    await asyncio.to_thread(full.unlink, missing_ok=True)
                    raise UploadTooLargeError(max_bytes)
                await asyncio.to_thread(handle.write, chunk)
        finally:
            if not handle.closed:
                await asyncio.to_thread(handle.close)
        return relative, total

    async def _buffer_bounded(
        self, file: UploadFile, relative: str, max_bytes: int
    ) -> tuple[str, int]:
        buffer = bytearray()
        while True:
            chunk = await file.read(_UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            buffer += chunk
            if len(buffer) > max_bytes:
                raise UploadTooLargeError(max_bytes)
        await asyncio.to_thread(self._backend.save, relative, bytes(buffer))
        return relative, len(buffer)

    def get_url(self, relative_path: str, user_id: str, expires_in: int | None = None) -> str:
        if isinstance(self._backend, LocalBackend):
            signed_path = generate_signed_url(relative_path, user_id, expires_in=expires_in)
            return f"{self._backend.base_url}{signed_path}"
        return self._backend.get_url(relative_path)

    def relative_path_from_url(self, stored_url: str | None) -> str | None:
        """Recover the storage key from a stored URL. Local URLs look like
        ``<base>/files/<rel>?<sig>``; S3 presigned URLs like
        ``<host>/<bucket>/<key>?<sig>``. Returns None when neither shape matches
        (empty / unknown / legacy value)."""
        if not stored_url:
            return None
        if isinstance(self._backend, LocalBackend):
            marker = "/files/"
            idx = stored_url.find(marker)
            if idx == -1:
                return None
            # generate_signed_url percent-encodes the path; undo that so callers
            # (e.g. resign_url -> get_url) get the raw path and don't double-encode.
            rel = unquote(stored_url[idx + len(marker) :].split("?", 1)[0])
            return rel or None
        # S3: object key sits after the /{bucket}/ prefix of the presigned URL.
        return self._extract_s3_relative(stored_url)

    def resign_url(
        self, stored_url: str | None, user_id: str, expires_in: int | None = None
    ) -> str | None:
        if not stored_url:
            return stored_url
        rel = self.relative_path_from_url(stored_url)
        if rel is None:
            return stored_url
        if isinstance(self._backend, LocalBackend):
            return self.get_url(rel, user_id, expires_in=expires_in)
        # S3: issue a fresh presigned URL for the same object key.
        return self._backend.get_url(rel)

    def _extract_s3_relative(self, url: str) -> str | None:
        parsed = urlparse(url)
        prefix = f"/{settings.S3_BUCKET_NAME}/"
        if parsed.path.startswith(prefix):
            # URL-decode: the S3 key is stored raw (may contain spaces/Cyrillic),
            # while the presigned URL percent-encodes it. Without unquote the key
            # gets double-encoded on re-signing (%20 -> %2520) and 404s.
            return unquote(parsed.path[len(prefix) :])
        return None

    async def save_bytes(self, relative_path: str, data: bytes) -> str:
        """Store bytes the caller already holds, under a path the caller chose.

        The save_upload* pair both derive their own random filename from an
        UploadFile; this is the primitive for content produced server-side (a
        re-encoded avatar), where the bytes are not the uploaded bytes and the
        path carries meaning."""
        await asyncio.to_thread(self._backend.save, relative_path, data)
        return relative_path

    def get_full_path(self, relative_path: str) -> str:
        return self._backend.get_full_path(relative_path)

    def exists(self, relative_path: str) -> bool:
        return self._backend.exists(relative_path)

    def presign_stream_url(self, relative_path: str, ttl_seconds: int) -> str:
        """Short-lived presigned S3 GET URL for direct video streaming (the
        ``/stream`` 302 target). S3 backend only — local delivery hands bytes to
        nginx via X-Accel-Redirect or falls back to FileResponse in dev."""
        if not isinstance(self._backend, S3Backend):
            raise RuntimeError("presign_stream_url requires the S3 storage backend")
        return self._backend.get_presigned_url(relative_path, ttl_seconds)

    def delete_file(self, relative_path: str) -> None:
        self._backend.delete(relative_path)

    @contextmanager
    def local_copy(self, relative_path: str):
        """Yield a valid local path for a stored file.

        LocalBackend hands back the real path and touches nothing. S3 streams
        the object into a temp file and removes it on exit — so callers that
        need a real file on disk (LibreOffice, FFmpeg, python-pptx) work the
        same on both backends.
        """
        if isinstance(self._backend, LocalBackend):
            yield self._backend.get_full_path(relative_path)
            return
        suffix = os.path.splitext(relative_path)[1]
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        tmp.close()
        try:
            self._backend.download_to(relative_path, tmp.name)
            yield tmp.name
        finally:
            if os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def save_file(self, relative_path: str, src_path: str) -> str:
        """Put a finished local file into storage under relative_path."""
        return self._backend.upload_from(relative_path, src_path)

    def list_prefix(self, prefix: str) -> list[str]:
        return self._backend.list_prefix(prefix)

    def delete_prefix(self, prefix: str) -> None:
        """Delete everything under a prefix (per-lesson and per-submission
        folders). Guarded: a blank or root-ish prefix would wipe the bucket.
        """
        clean = (prefix or "").strip().strip("/")
        if len(clean) < 3 or "/" not in clean:
            raise ValueError(f"refusing to delete an unsafe prefix: {prefix!r}")
        for key in self._backend.list_prefix(clean + "/"):
            try:
                self._backend.delete(key)
            except Exception:
                logger.warning("storage_prefix_delete_failed", key=key, exc_info=True)


storage_service = StorageService()
