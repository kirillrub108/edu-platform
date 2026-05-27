import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status

from app.config import settings
from app.dependencies import get_current_user
from app.limiter import limiter
from app.models.user import User
from app.schemas.auth import UserLogin, UserOut, UserRegister
from app.services.auth_service import AuthService, decode_token, get_auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


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
    return await service.register(
        email=data.email,
        password=data.password,
        full_name=data.full_name,
        role=data.role,
    )


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
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> Response:
    _clear_auth_cookies(response)
    # Best-effort: blacklist the access token and delete the refresh family
    # from Redis. Must not fail — clearing cookies is the primary action.
    access_cookie = request.cookies.get("access_token")
    refresh_cookie = request.cookies.get("refresh_token")
    if access_cookie:
        try:
            payload = decode_token(access_cookie, verify_exp=False)
            if payload.get("type") == "access" and payload.get("jti"):
                exp = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
                await service.logout(payload["jti"], exp, refresh_cookie)
        except Exception:
            pass
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    response: Response,
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    _clear_auth_cookies(response)
    await service.logout_all_sessions(str(user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
