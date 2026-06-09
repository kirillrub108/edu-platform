from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.quota import QuotaStatusRead
from app.services import quota_service

router = APIRouter(prefix="/api/v1/quota", tags=["quota"])


@router.get("", response_model=QuotaStatusRead)
async def get_quota(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await quota_service.get_status(db, user.id)
