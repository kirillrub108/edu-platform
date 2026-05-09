from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Response, status

from app.dependencies import get_current_token_payload, get_current_user
from app.models.user import User
from app.schemas.auth import (
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserLogin,
    UserOut,
    UserRegister,
)
from app.services.auth_service import AuthService, get_auth_service

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(
    data: UserRegister,
    service: AuthService = Depends(get_auth_service),
) -> User:
    return await service.register(
        email=data.email,
        password=data.password,
        full_name=data.full_name,
        role=data.role,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    data: UserLogin,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return await service.login(data.email, data.password, remember_me=data.remember_me)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    data: RefreshRequest,
    service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    return await service.refresh(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    data: LogoutRequest,
    payload: dict[str, Any] = Depends(get_current_token_payload),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    exp = datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc)
    await service.logout(payload["jti"], exp, data.refresh_token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    user: User = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
) -> Response:
    await service.logout_all_sessions(str(user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)) -> User:
    return user
