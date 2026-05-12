import os
import uuid
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from app.config import settings
from app.services.signed_url_service import generate_signed_url


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

    def get_url(self, relative_path: str, user_id: str) -> str:
        return f"{self.base_url}{generate_signed_url(relative_path, user_id)}"

    def resign_url(self, stored_url: str | None, user_id: str) -> str | None:
        """Take a previously-stored `/files/<rel>?...` URL and re-sign it for
        the given user. Stored URLs are signed for the lesson owner at write
        time; readers (the owner past 1h, or any other authorised user) need a
        fresh signature against their own `user_id`.
        """
        if not stored_url:
            return stored_url
        marker = "/files/"
        idx = stored_url.find(marker)
        if idx == -1:
            return stored_url
        rel_and_query = stored_url[idx + len(marker):]
        rel = rel_and_query.split("?", 1)[0]
        return self.get_url(rel, user_id)

    def get_full_path(self, relative_path: str) -> str:
        return str(self.base_path / relative_path)

    def delete_file(self, relative_path: str) -> None:
        full_path = self.base_path / relative_path
        if full_path.exists():
            full_path.unlink()


storage_service = StorageService()
