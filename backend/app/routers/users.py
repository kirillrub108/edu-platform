"""Own profile/privacy settings, avatar upload, public profile read, and the
account self-deletion entry point.

Thin by construction: parse → authorize → one or two service calls → return.
The privacy rule lives in profile_service, the deletion lifecycle in
account_service; neither is re-derived here.

None of these endpoints touch an LLM/vision/TTS provider or the credit ledger,
so they sit behind plain `get_current_user` and are intentionally absent from
AI_GATED_ENDPOINTS (same reasoning as routers/uploads.py, DECISIONS §50).
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import AVATAR_ALLOWED_EXTS, AVATAR_MAX_BYTES
from app.database import get_db
from app.dependencies import get_current_token_payload, get_current_user, get_optional_user
from app.limiter import limiter
from app.models.user import User
from app.schemas.auth import DeleteAccountRequest
from app.schemas.user import (
    PrivacySettingsOut,
    PrivacyUpdate,
    ProfileOut,
    ProfileSettingsOut,
    ProfileUpdate,
)
from app.services import account_service, file_validation_service, profile_service
from app.services.auth_service import AuthService, get_auth_service

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def _settings_out(user: User) -> ProfileSettingsOut:
    return ProfileSettingsOut(
        full_name=user.full_name,
        bio=user.bio,
        avatar_url=profile_service.avatar_url(user),
    )


# ── Own settings ─────────────────────────────────────────────────────────────


@router.get("/me/profile", response_model=ProfileSettingsOut)
async def read_my_profile(user: User = Depends(get_current_user)) -> ProfileSettingsOut:
    return _settings_out(user)


@router.patch("/me/profile", response_model=ProfileSettingsOut)
@limiter.limit("10/minute")
async def update_my_profile(
    request: Request,
    data: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileSettingsOut:
    # exclude_unset: an absent key means "leave it", an explicit null clears it.
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.commit()
    return _settings_out(user)


@router.get("/me/privacy", response_model=PrivacySettingsOut)
async def read_my_privacy(user: User = Depends(get_current_user)) -> User:
    return user


@router.patch("/me/privacy", response_model=PrivacySettingsOut)
@limiter.limit("10/minute")
async def update_my_privacy(
    request: Request,
    data: PrivacyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    for field, value in data.model_dump(exclude_unset=True, exclude_none=True).items():
        setattr(user, field, value)
    await db.commit()
    return user


# ── Avatar ───────────────────────────────────────────────────────────────────


@router.post("/me/avatar", response_model=ProfileSettingsOut)
@limiter.limit("5/minute")
async def upload_avatar(
    request: Request,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileSettingsOut:
    # Extension whitelist + real signature sniffing. SVG is absent from the
    # whitelist on purpose, and the magic check means renaming one to .png does
    # not get it past either — /files/* would serve it inline (stored XSS).
    await file_validation_service.validate_upload(
        file, AVATAR_ALLOWED_EXTS, enforce_size_limits=False
    )
    data = await file.read(AVATAR_MAX_BYTES + 1)
    if len(data) > AVATAR_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Файл слишком большой (максимум {AVATAR_MAX_BYTES // (1024 * 1024)} МБ)",
        )
    try:
        await profile_service.store_avatar(user, data)
    except OSError:
        # Pillow raises OSError on a truncated/undecodable image that still had
        # a valid magic prefix.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не удалось обработать изображение",
        )
    await db.commit()
    return _settings_out(user)


@router.delete("/me/avatar", response_model=ProfileSettingsOut)
async def delete_avatar(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileSettingsOut:
    """Drop the uploaded avatar. Any provider-supplied picture becomes visible
    again — that is what "revert to my Google avatar" means here."""
    profile_service.drop_avatar_file(user.id)
    user.avatar_image_path = None
    await db.commit()
    return _settings_out(user)


# ── Public profile ───────────────────────────────────────────────────────────


@router.get("/{user_id}/profile", response_model=ProfileOut)
async def read_profile(
    user_id: UUID,
    viewer: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
) -> ProfileOut:
    # include_deleted so a soft-deleted target is resolved and then refused by
    # the same 404 as a hidden one — never a distinguishable response.
    target = await account_service.get_user_including_deleted(db, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    access = await profile_service.resolve_profile_access(db, target, viewer)
    if not access.visible:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return await profile_service.get_profile(db, target, access)


# ── Account deletion ─────────────────────────────────────────────────────────


@router.post("/me/delete", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("3/minute")
async def delete_my_account(
    request: Request,
    data: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    payload: dict = Depends(get_current_token_payload),
    service: AuthService = Depends(get_auth_service),
    db: AsyncSession = Depends(get_db),
) -> Response:
    await account_service.delete_own_account(
        db, service, user=user, password=data.password, access_payload=payload
    )
    # 204 has no body to attach cookies to, so the deletion Response is built
    # here rather than via an injected `response` (same gotcha as /logout).
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    account_service.clear_auth_cookies(response)
    return response
