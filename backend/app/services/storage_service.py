import os
import uuid
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.config import settings


class StorageService:
    def __init__(self, base_path: str | None = None, base_url: str | None = None) -> None:
        self.base_path = Path(base_path or settings.STORAGE_PATH)
        self.base_url = (base_url or settings.BASE_URL).rstrip("/")
        self.base_path.mkdir(parents=True, exist_ok=True)

    async def save_upload(self, file: UploadFile, subfolder: str) -> str:
        safe_name = (file.filename or "file").replace("/", "_").replace("\\", "_")
        unique_name = f"{uuid.uuid4().hex}_{safe_name}"
        relative = os.path.join(subfolder, unique_name).replace("\\", "/")
        full_path = self.base_path / relative

        full_path.parent.mkdir(parents=True, exist_ok=True)

        async with aiofiles.open(full_path, "wb") as out:
            while chunk := await file.read(1024 * 1024):
                await out.write(chunk)

        return relative

    def get_url(self, relative_path: str) -> str:
        return f"{self.base_url}/files/{relative_path.lstrip('/')}"

    def get_full_path(self, relative_path: str) -> str:
        return str(self.base_path / relative_path)

    def delete_file(self, relative_path: str) -> None:
        full_path = self.base_path / relative_path
        if full_path.exists():
            full_path.unlink()


storage_service = StorageService()
