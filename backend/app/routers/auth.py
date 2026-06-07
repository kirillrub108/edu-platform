import secrets
from datetime import datetime, timezone
from uuid import UUID

import structlog
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.limiter import limiter
from app.models.user import User
from app.schemas.auth import UserLogin, UserOut, UserRegister
from app.services.auth_service import (
    AuthService,
    decode_token,
    generate_email_verification_token,
    get_auth_service,
    verify_email_verification_token,
)
from app.tasks.email_pipeline import send_email

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _enqueue_verification_email(user: User) -> None:
    """Mint a signed verification token and enqueue the verification email.
    Enqueue failures (e.g. broker down) are logged, never raised — registration
    and resend must not fail because mail couldn't be queued."""
    token = generate_email_verification_token(str(user.id))
    verify_url = f"{settings.BASE_URL}/api/v1/auth/verify-email?token={token}"
    try:
        send_email.delay(
            to=user.email,
            subject="Подтвердите ваш email — Edllm",
            template_name="verify_email.html",
            context={"full_name": user.full_name or "", "verify_url": verify_url},
        )
    except Exception:
        logger.warning("verification_email_enqueue_failed", user_id=str(user.id), exc_info=True)


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set httpOnly access + refresh cookies and a non-httpOnly CSRF token."""
    kw = {"samesite": settings.COOKIE_SAMESITE, "secure": settings.COOKIE_SECURE}
    response.set_cookie(
        "access_token", access_token,
        httponly=True, path="/",
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        **kw,
    )
    # Restrict refresh cookie to the one path that needs it so it is never
    # accidentally forwarded with ordinary API requests.
    response.set_cookie(
        "refresh_token", refresh_token,
        httponly=True, path="/api/v1/auth/refresh",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        **kw,
    )
    # Non-httpOnly so JS can read and forward it as X-CSRF-Token (double-submit).
    response.set_cookie(
        "csrf_token", secrets.token_hex(32),
        httponly=False, path="/",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400,
        **kw,
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/api/v1/auth/refresh")
    response.delete_cookie("csrf_token", path="/")


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
@limiter.limit("3/minute")
async def register(
    request: Request,
    data: UserRegister,
    service: AuthService = Depends(get_auth_service),
) -> User:
    user = await service.register(
        email=data.email,
        password=data.password,
        full_name=data.full_name,
        role=data.role,
    )
    _enqueue_verification_email(user)
    return user


@router.post("/login", status_code=status.HTTP_200_OK)
@limiter.limit("5/minute")
async def login(
    request: Request,
    response: Response,
    data: UserLogin,
    service: AuthService = Depends(get_auth_service),
) -> dict:
    tokens = await service.login(data.email, data.password, remember_me=data.remember_me)
    _set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
    return {}


@router.post("/refresh", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
    service: AuthService = Depends(get_auth_service),
) -> dict:
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token missing")
    tokens = await service.refresh(refresh_token)
    _set_auth_cookies(response, tokens.access_token, tokens.refresh_token)
    return {}


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    # Best-effort: blacklist the access token and revoke its refresh family in
    # Redis. Must not fail — clearing cookies is the primary action.
    access_cookie = request.cookies.get("access_token")
    if access_cookie:
        try:
            payload = decode_token(access_cookie, verify_exp=False)
            if payload.get("type") == "access" and payload.get("jti"):
                exp = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
                await service.logout(
                    payload["jti"],
                    exp,
                    user_id=payload.get("sub"),
                    family_id=payload.get("family_id"),
                )
        except Exception:
            pass
    # Clear cookies on the response we actually return: FastAPI sends the
    # returned Response, so headers set on an injected `response` param would be
    # discarded. delete_cookie must therefore target this object.
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookies(response)
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    await service.logout_all_sessions(str(user.id))
    # Same gotcha as /logout: clear cookies on the returned Response, not an
    # injected `response` param (which FastAPI would discard here).
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_auth_cookies(response)
    return response


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.get("/verify-email")
async def verify_email(
    token: str,
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    """Validate the signed token, flip email_verified to True (idempotent), and
    302 back to the SPA login. Invalid/expired tokens redirect with verified=0
    and a reason — never a 500."""
    try:
        user_id = verify_email_verification_token(token)
    except ValueError as exc:
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/login?verified=0&reason={exc}",
            status_code=status.HTTP_302_FOUND,
        )

    user = await db.scalar(select(User).where(User.id == UUID(user_id)))
    if user is None:
        return RedirectResponse(
            f"{settings.FRONTEND_URL}/login?verified=0&reason=not_found",
            status_code=status.HTTP_302_FOUND,
        )

    if not user.email_verified:
        user.email_verified = True
        await db.commit()

    return RedirectResponse(
        f"{settings.FRONTEND_URL}/login?verified=1",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/resend-verification", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/minute")
async def resend_verification(
    request: Request,
    user: User = Depends(get_current_user),
) -> Response:
    """Re-send the verification email to the logged-in user. Already-verified
    users get a 400 and no email is sent."""
    if user.email_verified:
        raise HTTPException(status_code=400, detail="Email already verified")
    _enqueue_verification_email(user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
