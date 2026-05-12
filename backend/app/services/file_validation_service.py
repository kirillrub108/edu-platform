"""Upload validation: extension whitelist, magic-byte sniffing, size caps,
and ZIP integrity checks. Defends against fake-extension uploads, oversized
payloads, ZIP bombs, and zip-slip path traversal — without an external scanner.
"""
import os
import zipfile
from io import BytesIO

from fastapi import HTTPException, UploadFile


SIZE_LIMITS: dict[str, int] = {
    ".pptx": 50 * 1024 * 1024,
    ".ppt":  50 * 1024 * 1024,
    ".pdf":  50 * 1024 * 1024,
    ".txt":  10 * 1024 * 1024,
    ".md":   10 * 1024 * 1024,
    ".markdown": 10 * 1024 * 1024,
    ".docx": 10 * 1024 * 1024,
    ".doc":  10 * 1024 * 1024,
    ".rtf":  10 * 1024 * 1024,
    ".odt":  10 * 1024 * 1024,
    ".html": 10 * 1024 * 1024,
    ".htm":  10 * 1024 * 1024,
    ".mp4":  500 * 1024 * 1024,
    ".webm": 500 * 1024 * 1024,
    ".mov":  500 * 1024 * 1024,
}

# Suffixes treated as suspicious when they appear *before* the final extension —
# catches double-extension tricks like "file.php.pdf" or "malware.exe.txt".
_DANGEROUS_INNER_EXTS: set[str] = {
    "exe", "php", "phtml", "js", "html", "htm", "sh", "bat", "cmd", "ps1",
    "py", "vbs", "scr", "com", "msi", "jar", "pl", "rb",
}

_ZIP_EXTS = {".pptx", ".docx", ".odt"}
_TEXT_EXTS = {".txt", ".md", ".markdown", ".html", ".htm", ".rtf"}

_MAX_ZIP_UNCOMPRESSED = 500 * 1024 * 1024
_MAX_ZIP_ENTRIES = 10_000


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def _ext(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


def _check_filename(filename: str, allowed_types: list[str]) -> str:
    if not filename:
        raise _bad("Filename is required")
    if "/" in filename or "\\" in filename:
        raise _bad("Invalid filename")

    ext = _ext(filename)
    if ext not in allowed_types:
        raise _bad(
            f"File type {ext or 'unknown'} not allowed. "
            f"Accepted: {', '.join(allowed_types)}"
        )

    # Double-extension trap: only flag when an *inner* segment looks like an
    # executable extension. Avoids rejecting legitimate names like
    # "report.v1.2.pdf" where the inner pieces are just version markers.
    parts = filename.lower().split(".")
    inner = parts[1:-1] if len(parts) >= 3 else []
    for piece in inner:
        if piece in _DANGEROUS_INNER_EXTS:
            raise _bad(f"Filename contains multiple extensions: {filename}")
    return ext


def _check_magic(head: bytes, sample: bytes, ext: str) -> None:
    if ext == ".pdf":
        if not head.startswith(b"%PDF"):
            raise _bad(f"File content does not match {ext}")
    elif ext in _ZIP_EXTS:
        if not head.startswith(b"PK\x03\x04"):
            raise _bad(f"File content does not match {ext}")
    elif ext == ".ppt":
        # Legacy PowerPoint: OLE2/CFB compound document.
        if head[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise _bad(f"File content does not match {ext}")
    elif ext == ".mp4":
        if head[4:8] != b"ftyp":
            raise _bad(f"File content does not match {ext}")
    elif ext in _TEXT_EXTS:
        # Plain-text formats: first 512 bytes must decode under some common
        # encoding. UTF-8 first; fall back to legacy Cyrillic / latin-1.
        decoded = False
        for enc in ("utf-8", "utf-8-sig", "cp1251", "windows-1251", "latin-1"):
            try:
                sample.decode(enc)
                decoded = True
                break
            except UnicodeDecodeError:
                continue
        if not decoded:
            raise _bad(f"File content does not look like text for {ext}")


def _check_zip(content: bytes) -> None:
    try:
        zf = zipfile.ZipFile(BytesIO(content))
    except zipfile.BadZipFile:
        raise _bad("Corrupted or invalid archive")

    try:
        entries = zf.infolist()
        if len(entries) > _MAX_ZIP_ENTRIES:
            raise _bad(f"Archive contains too many entries (>{_MAX_ZIP_ENTRIES})")
        total = 0
        for info in entries:
            normalized = info.filename.replace("\\", "/")
            if normalized.startswith("/") or ".." in normalized.split("/"):
                raise _bad("Archive entry path is invalid")
            total += info.file_size
            if total > _MAX_ZIP_UNCOMPRESSED:
                mb = _MAX_ZIP_UNCOMPRESSED // (1024 * 1024)
                raise _bad(f"Archive uncompressed size exceeds {mb}MB")
    finally:
        zf.close()


async def validate_upload(file: UploadFile, allowed_types: list[str]) -> None:
    """Raises HTTPException(400) if the upload fails extension, magic-byte,
    size, or ZIP-integrity checks. Always leaves the file pointer at offset 0
    so the caller can stream/read the file as if untouched.
    """
    ext = _check_filename(file.filename or "", allowed_types)

    max_size = SIZE_LIMITS.get(ext)
    if max_size is not None and file.size is not None and file.size > max_size:
        mb = max_size // (1024 * 1024)
        raise _bad(f"File too large. Maximum size for {ext} is {mb}MB")

    sample = await file.read(512)
    await file.seek(0)
    _check_magic(sample[:16], sample, ext)

    if ext in _ZIP_EXTS:
        content = await file.read()
        await file.seek(0)
        _check_zip(content)
