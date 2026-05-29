from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import CREDIT_WEIGHTS, PLAN_CONFIGS, TOPUP_PACKS
from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.models.user import User
from app.schemas.billing import (
    BalanceOut,
    GrantOut,
    GrantRequest,
    PlansOut,
    RenewalOut,
    TransactionOut,
)
from app.services import billing_service

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/balance", response_model=BalanceOut)
async def get_balance(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await billing_service.get_balance(db, user.id)


@router.get("/transactions", response_model=list[TransactionOut])
async def list_transactions(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await billing_service.get_transaction_history(db, user.id, limit=limit)


@router.get("/plans", response_model=PlansOut)
async def list_plans(_user: User = Depends(get_current_user)):
    return PlansOut(weights=CREDIT_WEIGHTS, plans=PLAN_CONFIGS, topup_packs=TOPUP_PACKS)


@router.post(
    "/admin/credits/grant",
    response_model=GrantOut,
    dependencies=[Depends(require_admin)],
)
async def admin_grant_credits(
    data: GrantRequest,
    db: AsyncSession = Depends(get_db),
):
    return await billing_service.grant_credits(db, data.user_id, data.amount, data.description)


@router.post(
    "/admin/renewal/run",
    response_model=RenewalOut,
    dependencies=[Depends(require_admin)],
)
async def admin_run_renewal(db: AsyncSession = Depends(get_db)):
    count = await billing_service.process_monthly_renewal(db)
    return RenewalOut(renewed_accounts=count)
