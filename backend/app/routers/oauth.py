"""Social sign-in routes. Thin by design: everything except HTTP shaping lives
in services/oauth_service.py, and the session itself is the ordinary one
(AuthService.issue_session + the shared _set_auth_cookies)."""

from urllib.parse import urlencode

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import OAUTH_FAILURE_PATH, OAUTH_REGISTER_PATH
from app.database import get_db
from app.limiter import limiter
from app.redis_client import get_redis
from app.routers.auth import _set_auth_cookies
from app.schemas.oauth import OAuthCompleteRequest, OAuthStartRequest, OAuthStartResponse
from app.services import oauth_service
from app.services.auth_service import AuthService, get_auth_service
from app.services.oauth_service import OAuthError, Provider
from app.services.webhook_security import resolve_client_ip

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/auth/oauth", tags=["auth"])


def _require_provider(provider: str) -> Provider:
    """404 for both an unknown provider and a configured-but-disabled one — a
    disabled provider is simply not part of this deployment's surface."""
    configured = oauth_service.get_provider(provider)
    if configured is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Unknown OAuth provider")
    return configured


def _failure_redirect(reason: str) -> RedirectResponse:
    query = urlencode({"oauth": "0", "reason": reason})
    return RedirectResponse(
        f"{settings.FRONTEND_URL}{OAUTH_FAILURE_PATH}?{query}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/{provider}/start", response_model=OAuthStartResponse)
@limiter.limit("5/minute")
async def oauth_start(
    request: Request,
    provider: str,
    data: OAuthStartRequest,
    redis: Redis = Depends(get_redis),
) -> OAuthStartResponse:
    """Return the provider's authorize URL. The SPA navigates to it with a full
    page load — this endpoint never talks to the provider itself."""
    configured = _require_provider(provider)
    authorize_url = await oauth_service.start(
        redis,
        configured,
        remember_me=data.remember_me,
        next_path=data.next,
    )
    return OAuthStartResponse(authorize_url=authorize_url)


@router.get("/{provider}/callback")
@limiter.limit("10/minute")
async def oauth_callback(
    request: Request,
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    service: AuthService = Depends(get_auth_service),
) -> RedirectResponse:
    """The provider's redirect target. Public and GET, so no CSRF applies; the
    single-use state is what binds the response to a flow we started. Every
    failure — ours or the provider's — leaves as a 302 with a reason code."""
    configured = _require_provider(provider)

    if error:
        # User declined on the consent screen, or the provider refused outright.
        return _failure_redirect("access_denied" if error == "access_denied" else "provider_error")
    if not code or not state:
        return _failure_redirect("invalid_request")

    try:
        flow = await oauth_service.consume_state(redis, configured, state)
        profile = await oauth_service.fetch_profile(configured, code, flow.code_verifier)
        user = await oauth_service.resolve_user(db, profile)
    except OAuthError as exc:
        logger.info("oauth_callback_failed", provider=provider, reason=exc.reason)
        return _failure_redirect(exc.reason)
    except Exception:
        logger.warning("oauth_callback_error", provider=provider, exc_info=True)
        return _failure_redirect("internal_error")

    if user is None:
        # Branch C: unknown identity and unknown mailbox. No user row yet — the
        # SPA still has to collect a role and the mandatory consents.
        ticket = await oauth_service.issue_ticket(redis, profile)
        query = urlencode({"oauth_pending": ticket, "provider": provider})
        logger.info("oauth_pending_issued", provider=provider)
        return RedirectResponse(
            f"{settings.FRONTEND_URL}{OAUTH_REGISTER_PATH}?{query}",
            status_code=status.HTTP_302_FOUND,
        )

    tokens = await service.issue_session(user, remember_me=flow.remember_me)
    destination = flow.next or oauth_service.dashboard_path(user)
    response = RedirectResponse(
        f"{settings.FRONTEND_URL}{destination}",
        status_code=status.HTTP_302_FOUND,
    )
    # Cookies must be set on the returned Response — an injected `response`
    # param would be discarded here, same gotcha as /logout.
    _set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
    logger.info("oauth_login", provider=provider, user_id=str(user.id))
    return response


@router.post("/complete", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def oauth_complete(
    request: Request,
    response: Response,
    data: OAuthCompleteRequest,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    service: AuthService = Depends(get_auth_service),
) -> dict[str, str]:
    """Finish branch C: burn the ticket, create the account with its consent
    record, and sign the user in on the usual cookies."""
    try:
        pending = await oauth_service.consume_ticket(redis, data.ticket)
        user = await oauth_service.create_user(
            db,
            pending,
            role=data.role,
            accepted_marketing=data.marketing_consent,
            consent_ip=resolve_client_ip(request),
        )
    except OAuthError as exc:
        raise HTTPException(status_code=400, detail=exc.reason)

    tokens = await service.issue_session(user)
    _set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
    logger.info("oauth_registered", provider=pending.provider, user_id=str(user.id))
    return {"redirect": oauth_service.dashboard_path(user)}
