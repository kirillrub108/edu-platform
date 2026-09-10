"""Authenticity checks for inbound provider webhooks.

Two providers, two mechanisms — both live here so no router grows its own copy.

YooKassa (source IP)
--------------------

YooKassa signs nothing on the notification; authenticity is established by
re-fetching the payment from its API. As defence in depth we also reject calls
whose real client IP is outside the published YooKassa ranges
(constants.YOOKASSA_TRUSTED_CIDRS — an overridable fallback; the authoritative
source is the YooKassa docs / SDK SecurityHelper).

The real client IP is taken from X-Forwarded-For ONLY when the immediate TCP
peer is a configured trusted proxy (loopback / docker network / prod nginx) —
never from an arbitrary header — so an attacker hitting the backend directly
cannot spoof a trusted source.

Resend (Svix signature)
-----------------------
Resend signs each delivery event with Svix: the HMAC-SHA256 of
``{svix-id}.{svix-timestamp}.{raw body}`` under the base64 secret that follows
the ``whsec_`` prefix. ``svix-signature`` carries a space-separated list of
``v1,<base64>`` candidates (Svix rotates keys by sending several), so a match
against any one is a pass. The timestamp is checked against our clock first,
which bounds how long a captured request stays replayable; exact single-event
replay is stopped separately by the svix-id dedup in email_suppression_service.

Verification is on stdlib hmac — the whole scheme is nine lines and a Svix SDK
would be a dependency for no gain.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import time
from collections.abc import Iterable

from fastapi import Request

from app.constants import (
    RESEND_WEBHOOK_TOLERANCE_SECONDS,
    YOOKASSA_TRUSTED_CIDRS,
    YOOKASSA_TRUSTED_PROXIES,
)


def _in_networks(ip: str, cidrs: Iterable[str]) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for cidr in cidrs:
        try:
            if addr in ipaddress.ip_network(cidr, strict=False):
                return True
        except ValueError:
            continue
    return False


def resolve_client_ip(request: Request) -> str | None:
    """The real client IP. X-Forwarded-For is honoured only when the TCP peer is
    a trusted proxy (or absent, as under the ASGI test transport); the rightmost
    non-proxy hop is the originating client."""
    peer = request.client.host if request.client else None
    xff = request.headers.get("x-forwarded-for")
    if xff and (peer is None or _in_networks(peer, YOOKASSA_TRUSTED_PROXIES)):
        for hop in reversed([p.strip() for p in xff.split(",") if p.strip()]):
            if not _in_networks(hop, YOOKASSA_TRUSTED_PROXIES):
                return hop
        return peer
    return peer


def is_trusted_yookassa_ip(ip: str | None) -> bool:
    return bool(ip) and _in_networks(ip, YOOKASSA_TRUSTED_CIDRS)


def verify_svix_signature(
    *,
    secret: str,
    svix_id: str | None,
    svix_timestamp: str | None,
    svix_signature: str | None,
    body: bytes,
) -> bool:
    """True if `body` carries a valid Svix signature under `secret`.

    Returns False (never raises) for anything malformed — a missing header, a
    non-numeric timestamp, a bad base64 secret — so the caller has exactly one
    rejection path.
    """
    if not secret or not svix_id or not svix_timestamp or not svix_signature:
        return False
    try:
        sent_at = int(svix_timestamp)
    except ValueError:
        return False
    if abs(time.time() - sent_at) > RESEND_WEBHOOK_TOLERANCE_SECONDS:
        return False

    try:
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except (ValueError, base64.binascii.Error):
        return False

    signed = f"{svix_id}.{svix_timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    # Space-separated "v1,<sig>" candidates; versions other than v1 are ignored.
    for candidate in svix_signature.split():
        version, _, value = candidate.partition(",")
        if version == "v1" and hmac.compare_digest(value, expected):
            return True
    return False
