from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import settings
from app.services.signed_url_service import verify_signed_url

router = APIRouter(tags=["files"])


@router.get("/files/{file_path:path}")
async def serve_file(
    file_path: str,
    uid: str = Query(...),
    expires: int = Query(...),
    sig: str = Query(...),
):
    if ".." in file_path.split("/") or file_path.startswith("/") or "\\" in file_path:
        raise HTTPException(status_code=403, detail="Invalid path")

    if not verify_signed_url(file_path, uid, expires, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired signature")

    storage_root = Path(settings.STORAGE_PATH).resolve()
    full_path = (storage_root / file_path).resolve()

    try:
        full_path.relative_to(storage_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="Invalid path")

    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(str(full_path))
