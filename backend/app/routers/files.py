import logging
import mimetypes
from pathlib import Path

import aiofiles
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.services.signed_url_service import verify_signed_url

logger = logging.getLogger(__name__)
router = APIRouter(tags=["files"])

CHUNK_SIZE = 1024 * 1024  # 1 MB


def _resolve_path(file_path: str) -> Path:
    if ".." in file_path.split("/") or file_path.startswith("/") or "\\" in file_path:
        raise HTTPException(status_code=400, detail="Invalid path")
    storage_root = Path(settings.STORAGE_PATH).resolve()
    full_path = (storage_root / file_path).resolve()
    try:
        full_path.relative_to(storage_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    if not full_path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return full_path


async def _stream_file(path: Path, start: int, end: int):
    async with aiofiles.open(path, "rb") as f:
        await f.seek(start)
        remaining = end - start + 1
        while remaining > 0:
            chunk = await f.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk


@router.get("/files/{file_path:path}")
async def serve_file(
    request: Request,
    file_path: str,
    uid: str = Query(...),
    expires: int = Query(...),
    sig: str = Query(...),
):
    if ".." in file_path.split("/") or file_path.startswith("/") or "\\" in file_path:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not verify_signed_url(file_path, uid, expires, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired signature")

    full_path = _resolve_path(file_path)
    file_size = full_path.stat().st_size
    content_type = mimetypes.guess_type(full_path.name)[0] or "application/octet-stream"

    range_header = request.headers.get("Range")
    if not range_header:
        return StreamingResponse(
            _stream_file(full_path, 0, file_size - 1),
            media_type=content_type,
            headers={"Accept-Ranges": "bytes", "Content-Length": str(file_size)},
        )

    # Parse "bytes=start-end"
    try:
        unit, ranges = range_header.split("=", 1)
        if unit.strip() != "bytes":
            raise ValueError
        raw_start, _, raw_end = ranges.partition("-")
        start = int(raw_start) if raw_start else 0
        end = int(raw_end) if raw_end else file_size - 1
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Invalid Range header")

    if start < 0 or end >= file_size or start > end:
        raise HTTPException(
            status_code=416,
            detail="Range Not Satisfiable",
            headers={"Content-Range": f"bytes */{file_size}"},
        )

    chunk_size = end - start + 1
    return StreamingResponse(
        _stream_file(full_path, start, end),
        status_code=206,
        media_type=content_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(chunk_size),
        },
    )
