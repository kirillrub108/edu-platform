import asyncio
import io
import os
import uuid
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from fastapi import UploadFile

from app.config import settings
from app.services.signed_url_service import generate_signed_url


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

    def get_url(self, relative_path: str, user_id: str) -> str:
        if isinstance(self._backend, LocalBackend):
            return f"{self._backend.base_url}{generate_signed_url(relative_path, user_id)}"
        return self._backend.get_url(relative_path)

    def resign_url(self, stored_url: str | None, user_id: str) -> str | None:
        if not stored_url:
            return stored_url
        if isinstance(self._backend, LocalBackend):
            marker = "/files/"
            idx = stored_url.find(marker)
            if idx == -1:
                return stored_url
            rel_and_query = stored_url[idx + len(marker):]
            rel = rel_and_query.split("?", 1)[0]
            return self.get_url(rel, user_id)
        # S3: extract the object key from the presigned URL and issue a fresh one.
        # Presigned URL path is /{bucket}/{key}, so strip the bucket prefix.
        rel = self._extract_s3_relative(stored_url)
        if rel is None:
            return stored_url
        return self._backend.get_url(rel)

    def _extract_s3_relative(self, url: str) -> str | None:
        parsed = urlparse(url)
        prefix = f"/{settings.S3_BUCKET_NAME}/"
        if parsed.path.startswith(prefix):
            return parsed.path[len(prefix):]
        return None

    def get_full_path(self, relative_path: str) -> str:
        return self._backend.get_full_path(relative_path)

    def delete_file(self, relative_path: str) -> None:
        self._backend.delete(relative_path)


storage_service = StorageService()
