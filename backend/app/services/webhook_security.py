"""Source-IP verification for the YooKassa webhook.

YooKassa signs nothing on the notification; authenticity is established by
re-fetching the payment from its API. As defence in depth we also reject calls
whose real client IP is outside the published YooKassa ranges
(constants.YOOKASSA_TRUSTED_CIDRS — an overridable fallback; the authoritative
source is the YooKassa docs / SDK SecurityHelper).

The real client IP is taken from X-Forwarded-For ONLY when the immediate TCP
peer is a configured trusted proxy (loopback / docker network / prod nginx) —
never from an arbitrary header — so an attacker hitting the backend directly
cannot spoof a trusted source.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

from fastapi import Request

from app.constants import YOOKASSA_TRUSTED_CIDRS, YOOKASSA_TRUSTED_PROXIES


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
