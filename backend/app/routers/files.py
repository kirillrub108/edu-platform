import structlog
import mimetypes
import time
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import aiofiles
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from app.config import settings
from app.services.signed_url_service import verify_signed_url

logger = structlog.get_logger()
router = APIRouter(tags=["files"])
# Internal-only routes (called by nginx auth_request, not browsers).
internal_router = APIRouter(tags=["files"])

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

    # NOTE: this dev-only route (registered when SERVE_STATIC_VIA_NGINX=false)
    # intentionally still serves /files/videos/* as signed bearer URLs — it's the
    # 302 target the /stream endpoint redirects to in dev, so the browser fetches
    # video bytes directly instead of through the Nuxt proxy. In prod nginx serves
    # /files/* and the video path is blocked in verify_file_signature below.
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


@internal_router.get("/internal/files/verify")
async def verify_file_signature(request: Request) -> Response:
    """auth_request target for nginx (prod static delivery).

    nginx forwards the original request line in `X-Original-URI`; we re-run the
    existing HMAC check via `verify_signed_url` and, on success, return the
    remaining signature lifetime in `X-Signed-TTL` so nginx can cap
    `Cache-Control: max-age` to it (an expired URL can't linger in the CDN).
    Returns 200 to let nginx serve the file, 403 otherwise — auth_request maps
    any other status to 500, so only these two are ever returned.
    """
    original = request.headers.get("X-Original-URI", "")
    parsed = urlparse(original)
    if not parsed.path.startswith("/files/"):
        raise HTTPException(status_code=403, detail="Forbidden")

    file_path = unquote(parsed.path[len("/files/"):])
    if file_path.split("/", 1)[0] == "videos":
        # Videos are served only via the authorised /stream endpoint; refuse to
        # validate a signed /files/videos/* URL so the old path can't be replayed.
        raise HTTPException(status_code=403, detail="Forbidden")
    params = parse_qs(parsed.query)
    uid = (params.get("uid") or [""])[0]
    sig = (params.get("sig") or [""])[0]
    try:
        expires = int((params.get("expires") or ["0"])[0])
    except ValueError:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not uid or not sig or not verify_signed_url(file_path, uid, expires, sig):
        raise HTTPException(status_code=403, detail="Forbidden")

    ttl = max(expires - int(time.time()), 0)
    return Response(status_code=200, headers={"X-Signed-TTL": str(ttl)})
