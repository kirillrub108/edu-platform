"""Can we plausibly mail this address at all?

Two independent gates, both applied before an account is created or an address
is changed:

  * *suppression* — the address already hard-bounced or complained. A definite
    no; there is nothing to probe.
  * *DNS* — the domain publishes an MX record, or (RFC 5321 §5.1 implicit-MX
    fallback) an A/AAAA record. Neither means no mail server can ever be found
    for it, so a verification email would bounce with certainty.

What this deliberately cannot do: prove a *mailbox* exists. Only sending finds
that out. `casdsa@dsa.da` is caught because `dsa.da` resolves to nothing;
`nobody@gmail.com` is not, and is caught later by the bounce webhook.

Failure is open. A DNS timeout or a broken resolver is our outage, not the
user's, and blocking sign-ups over it would be a self-inflicted incident — so a
lookup that cannot complete logs a WARNING and lets the address through. Only
NXDOMAIN — an authoritative "this name does not exist" — is a rejection.

That distinction is why `DNS_RESOLVERS` exists: inside a Docker network
/etc/resolv.conf points at the embedded stub at 127.0.0.11, which answers
SERVFAIL for a bogus domain instead of passing NXDOMAIN through. SERVFAIL is
unknown, so with the default resolver the probe fails open on exactly the
addresses it is meant to catch. Point it at a real recursive resolver.
"""

from __future__ import annotations

import dns.asyncresolver
import dns.exception
import dns.resolver
import structlog
from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import DNS_DOMAIN_CACHE_TTL_SECONDS, DNS_RESOLVE_TIMEOUT_SECONDS
from app.services import email_suppression_service

logger = structlog.get_logger()

# Stable machine codes; the SPA maps them to copy, so they must not drift.
UNDELIVERABLE_DOMAIN_CODE = "undeliverable_email_domain"
SUPPRESSED_EMAIL_CODE = "email_suppressed"


def _cache_key(domain: str) -> str:
    return f"email_domain_mx:{domain}"


def _ascii_domain(domain: str) -> str | None:
    """IDNA-encode `domain` for the resolver. A Cyrillic domain must be sent as
    punycode — handing the resolver raw non-ASCII raises, which would land in
    the fail-open path and silently mask a genuinely dead domain. None if the
    label set is not encodable at all, which is itself a hard no."""
    try:
        return domain.encode("idna").decode("ascii")
    except (UnicodeError, UnicodeDecodeError):
        return None


async def _resolve_has_mail_host(domain: str) -> bool | None:
    """True/False if DNS answered, None if it could not be reached.

    None is the fail-open signal: it means "unknown", not "no".
    """
    resolver = dns.asyncresolver.Resolver()
    resolver.timeout = DNS_RESOLVE_TIMEOUT_SECONDS
    resolver.lifetime = DNS_RESOLVE_TIMEOUT_SECONDS
    nameservers = [ns.strip() for ns in settings.DNS_RESOLVERS.split(",") if ns.strip()]
    if nameservers:
        resolver.nameservers = nameservers

    for rdtype in ("MX", "A", "AAAA"):
        try:
            answer = await resolver.resolve(domain, rdtype)
            if len(answer) > 0:
                return True
        except dns.resolver.NoAnswer:
            # The name exists but has no record of this type; fall through to
            # the next one in the MX → A → AAAA chain.
            continue
        except dns.resolver.NXDOMAIN:
            # Authoritative "no such name" — the only answer worth rejecting on.
            return False
        except (dns.exception.DNSException, OSError):
            # Timeout, SERVFAIL (NoNameservers), no configured resolver: the
            # lookup did not conclude. Unknown, never "no" — a domain whose
            # nameservers are briefly broken must not cost its owner a sign-up.
            return None
    return False


async def domain_accepts_mail(redis: Redis, domain: str) -> bool:
    """Cached MX/A verdict for `domain`. True whenever the answer is unknown."""
    domain = domain.strip().lower().rstrip(".")
    ascii_domain = _ascii_domain(domain)
    if ascii_domain is None:
        logger.info("email_domain_not_idna", domain=domain)
        return False

    key = _cache_key(ascii_domain)
    try:
        cached = await redis.get(key)
    except Exception:
        # Redis being down must not take registration with it; just skip the cache.
        cached = None
    if cached is not None:
        return cached == "1"

    verdict = await _resolve_has_mail_host(ascii_domain)
    if verdict is None:
        logger.warning("email_domain_dns_unavailable", domain=ascii_domain)
        return True

    try:
        await redis.set(key, "1" if verdict else "0", ex=DNS_DOMAIN_CACHE_TTL_SECONDS)
    except Exception:
        logger.warning("email_domain_cache_write_failed", domain=ascii_domain, exc_info=True)
    return verdict


async def assert_deliverable(db: AsyncSession, redis: Redis, email: str) -> None:
    """Gate an address before we commit to mailing it. Raises 422 with a stable
    code, or returns None. Shared by register, resend-verification and
    change-email so the three cannot drift apart."""
    if await email_suppression_service.is_suppressed(db, email):
        raise HTTPException(status_code=422, detail=SUPPRESSED_EMAIL_CODE)

    domain = email.rsplit("@", 1)[-1]
    if not await domain_accepts_mail(redis, domain):
        raise HTTPException(status_code=422, detail=UNDELIVERABLE_DOMAIN_CODE)
