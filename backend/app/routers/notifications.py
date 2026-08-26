"""Notification preferences + public one-click unsubscribe.

The unsubscribe routes are deliberately unauthenticated: a mail client acting on
`List-Unsubscribe-Post` carries no cookies. The signed token is the whole
authorization, and it can express nothing but "switch off category C for user
U", so it is not a general-purpose credential.
"""

from __future__ import annotations

from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import NOTIFY_UNSUBSCRIBED_PATH
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.notification import NotificationSettingsRead, NotificationSettingsUpdate
from app.services.notification_service import verify_unsubscribe_token

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

logger = structlog.get_logger()


@router.get("/settings", response_model=NotificationSettingsRead)
async def get_settings(user: User = Depends(get_current_user)) -> NotificationSettingsRead:
    return NotificationSettingsRead.model_validate(user)


@router.patch("/settings", response_model=NotificationSettingsRead)
async def update_settings(
    data: NotificationSettingsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> NotificationSettingsRead:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(user, field, value)
    await db.commit()
    return NotificationSettingsRead.model_validate(user)


async def _apply_unsubscribe(db: AsyncSession, token: str) -> str:
    """Switch off the token's category. Returns a status code for the caller to
    surface: 'ok' | 'expired' | 'invalid' | 'not_found'. Idempotent — a second
    click on the same link is another 'ok'."""
    try:
        user_id, category = verify_unsubscribe_token(token)
    except ValueError as exc:
        return str(exc)

    user = await db.scalar(select(User).where(User.id == UUID(user_id)))
    if user is None:
        return "not_found"
    setattr(user, category.value, False)
    await db.commit()
    logger.info("notification_unsubscribed", user_id=user_id, category=category.value)
    return "ok"


@router.get("/unsubscribe")
async def unsubscribe(token: str, db: AsyncSession = Depends(get_db)) -> RedirectResponse:
    """Human click from the mail footer — always redirects to the SPA, never a
    5xx, so a stale link lands on an explanation instead of an error page."""
    result = await _apply_unsubscribe(db, token)
    return RedirectResponse(
        f"{settings.FRONTEND_URL}{NOTIFY_UNSUBSCRIBED_PATH}?status={result}",
        status_code=status.HTTP_302_FOUND,
    )


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
async def unsubscribe_one_click(token: str, db: AsyncSession = Depends(get_db)) -> Response:
    """RFC 8058 target for `List-Unsubscribe-Post`. Mail clients ignore the body,
    so this answers 204 whatever the token turned out to be."""
    await _apply_unsubscribe(db, token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
