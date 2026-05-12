"""HMAC-signed URL generation and verification for protected static files.

The signature is computed over `"{file_path}:{user_id}:{expires_at}"` using
HMAC-SHA256 with `settings.SECRET_KEY`. Verification uses `hmac.compare_digest`
to avoid timing side-channels. The signature *is* the auth mechanism for
`/files/*` — no JWT is required at the file endpoint.
"""
import hashlib
import hmac
import time
from urllib.parse import urlencode

from app.config import settings


def _sign(payload: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _normalize(file_path: str) -> str:
    return file_path.lstrip("/").replace("\\", "/")


def generate_signed_url(
    file_path: str, user_id: str, expires_in: int | None = None
) -> str:
    """Return a signed URL path: `/files/<file_path>?expires=...&sig=...`.

    `user_id` is folded into the HMAC payload but never serialised into the URL
    — the file endpoint reads it from the caller's JWT instead, so it never
    appears in server logs, browser history, or Referer headers.
    Callers that need a fully-qualified URL prepend `settings.BASE_URL`.
    """
    if expires_in is None:
        expires_in = settings.SIGNED_URL_EXPIRES_IN
    expires_at = int(time.time()) + int(expires_in)
    clean_path = _normalize(file_path)
    payload = f"{clean_path}:{user_id}:{expires_at}"
    sig = _sign(payload)
    query = urlencode({"expires": expires_at, "sig": sig})
    return f"/files/{clean_path}?{query}"


def verify_signed_url(
    file_path: str, user_id: str, expires: int, sig: str
) -> bool:
    if expires <= int(time.time()):
        return False
    clean_path = _normalize(file_path)
    payload = f"{clean_path}:{user_id}:{expires}"
    expected = _sign(payload)
    return hmac.compare_digest(expected, sig)
