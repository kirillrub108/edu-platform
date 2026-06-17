import uuid
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.constants import (
    AUTO_CHARS_PER_SLIDE,
    CREDIT_PACKAGES,
    CREDIT_WEIGHTS,
    PLAN_CONFIGS,
    TTS_CHARS_PER_CREDIT,
    VIDEO_AUTO_BASE_CREDITS,
    VIDEO_TEXT_BASE_CREDITS,
)
from app.database import get_db
from app.dependencies import get_current_user, require_admin
from app.limiter import limiter
from app.models.payment import Payment, PaymentStatus
from app.models.user import User
from app.schemas.billing import (
    BalanceOut,
    GrantOut,
    GrantRequest,
    PaymentCreateOut,
    PaymentCreateRequest,
    PaymentOut,
    PlansOut,
    RenewalOut,
    TransactionOut,
    TrialOut,
    VideoPricingOut,
)
from app.services import billing_service, quota_service, yookassa_service

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/billing", tags=["billing"])


@router.get("/balance", response_model=BalanceOut)
async def get_balance(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    bal = await billing_service.get_balance(db, user.id)
    trial = await quota_service.get_trial_state(db, user.id)
    return BalanceOut(**bal, trial=TrialOut(**trial))


@router.get("/transactions", response_model=list[TransactionOut])
async def list_transactions(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await billing_service.get_transaction_history(db, user.id, limit=limit)


@router.get("/plans", response_model=PlansOut)
async def list_plans(_user: User = Depends(get_current_user)):
    return PlansOut(
        weights=CREDIT_WEIGHTS,
        plans=PLAN_CONFIGS,
        packages=CREDIT_PACKAGES,
        video_pricing=VideoPricingOut(
            text_base=VIDEO_TEXT_BASE_CREDITS,
            auto_base=VIDEO_AUTO_BASE_CREDITS,
            chars_per_credit=TTS_CHARS_PER_CREDIT,
            auto_chars_per_slide=AUTO_CHARS_PER_SLIDE,
        ),
    )


# ── YooKassa payments ─────────────────────────────────────────────────────────


@router.post("/payments", response_model=PaymentCreateOut)
@limiter.limit("10/minute")
async def create_payment(
    request: Request,
    data: PaymentCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    package = CREDIT_PACKAGES.get(data.package_key)
    if package is None:
        raise HTTPException(status_code=400, detail="Неизвестный пакет кредитов")
    if not yookassa_service.is_configured():
        raise HTTPException(status_code=503, detail="Платежи временно недоступны")

    payment = Payment(
        user_id=user.id,
        package_key=data.package_key,
        amount_rub=package["price_rub"],
        credits=package["credits"],
        status=PaymentStatus.pending,
        idempotence_key=uuid.uuid4().hex,
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    try:
        yk = await yookassa_service.create_payment(
            amount_rub=f"{package['price_rub']:.2f}",
            description=f"Edllm: пакет {package['credits']} кредитов",
            idempotence_key=payment.idempotence_key,
            metadata={"payment_id": str(payment.id), "package_key": data.package_key},
            credits=package["credits"],
            customer_email=user.email,
            # payment_id in the return URL lets the billing page poll the right
            # payment after the buyer comes back from checkout.
            return_url=f"{yookassa_service.base_return_url()}?payment_id={payment.id}",
        )
    except yookassa_service.YooKassaError as exc:
        payment.status = PaymentStatus.canceled
        await db.commit()
        logger.error("payment_create_failed", payment_id=str(payment.id), error=str(exc))
        raise HTTPException(status_code=502, detail="Платёжный сервис недоступен")

    confirmation_url = yk.confirmation.confirmation_url if yk.confirmation else None
    if not confirmation_url:
        payment.status = PaymentStatus.canceled
        await db.commit()
        logger.error("payment_no_confirmation_url", payment_id=str(payment.id))
        raise HTTPException(status_code=502, detail="Платёжный сервис недоступен")

    payment.yookassa_payment_id = yk.id
    await db.commit()
    return PaymentCreateOut(payment_id=payment.id, confirmation_url=confirmation_url)


async def _settle_from_yookassa(db: AsyncSession, payment: Payment) -> None:
    """Pull the authoritative status from YooKassa and settle idempotently.
    Network errors leave the payment pending — the caller keeps polling."""
    if payment.status != PaymentStatus.pending or not payment.yookassa_payment_id:
        return
    try:
        yk = await yookassa_service.get_payment(payment.yookassa_payment_id)
    except yookassa_service.YooKassaError:
        return
    yk_status = yk.status
    if yk_status == "succeeded":
        await billing_service.apply_purchase(db, payment.id)
    elif yk_status == "canceled":
        await billing_service.mark_payment_canceled(db, payment.id)


@router.get("/payments", response_model=list[PaymentOut])
async def list_payments(
    limit: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Payment)
        .where(Payment.user_id == user.id)
        .order_by(Payment.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


@router.get("/payments/{payment_id}", response_model=PaymentOut)
async def get_payment(
    payment_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    payment = await db.scalar(
        select(Payment).where(Payment.id == payment_id, Payment.user_id == user.id)
    )
    if payment is None:
        raise HTTPException(status_code=404, detail="Payment not found")
    # Polling doubles as settlement so local/dev flows work without a publicly
    # reachable webhook; apply_purchase is idempotent against the webhook path.
    await _settle_from_yookassa(db, payment)
    await db.refresh(payment)
    return payment


@router.post("/webhooks/yookassa")
async def yookassa_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """YooKassa HTTP notification. The body is NEVER trusted: only object.id is
    read, then the payment is re-fetched from the YooKassa API and settled
    idempotently. Redelivery of a processed event is a no-op. Deliberately has
    no cookie-auth dependency — that keeps it outside the CSRF double-submit
    check without weakening any other route.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    yk_id = ((body or {}).get("object") or {}).get("id")
    if not yk_id or not isinstance(yk_id, str):
        # Garbage / foreign notification — acknowledge so YooKassa stops retrying.
        return {"ok": True}

    payment = await db.scalar(
        select(Payment).where(Payment.yookassa_payment_id == yk_id)
    )
    if payment is None:
        logger.warning("yookassa_webhook_unknown_payment", yookassa_payment_id=yk_id)
        return {"ok": True}

    try:
        yk = await yookassa_service.get_payment(yk_id)
    except yookassa_service.YooKassaNotFound:
        logger.warning("yookassa_webhook_payment_not_found", yookassa_payment_id=yk_id)
        return {"ok": True}
    except yookassa_service.YooKassaError:
        # Verification temporarily impossible — 503 makes YooKassa redeliver.
        raise HTTPException(status_code=503, detail="Verification unavailable")

    yk_status = yk.status
    if yk_status == "succeeded":
        await billing_service.apply_purchase(db, payment.id)
    elif yk_status == "canceled":
        await billing_service.mark_payment_canceled(db, payment.id)
    return {"ok": True}


# ── Admin ─────────────────────────────────────────────────────────────────────


@router.post(
    "/admin/credits/grant",
    response_model=GrantOut,
    dependencies=[Depends(require_admin)],
)
async def admin_grant_credits(
    data: GrantRequest,
    db: AsyncSession = Depends(get_db),
):
    tx = await billing_service.grant_credits(db, data.user_id, data.amount, data.description)
    bal = await billing_service.get_balance(db, data.user_id)
    return GrantOut(
        id=tx.id,
        account_id=tx.account_id,
        delta=tx.delta,
        created_at=tx.created_at,
        balance=bal["balance"],
        reserved=bal["reserved"],
        available=bal["available"],
    )


@router.post(
    "/admin/renewal/run",
    response_model=RenewalOut,
    dependencies=[Depends(require_admin)],
)
async def admin_run_renewal(db: AsyncSession = Depends(get_db)):
    count = await billing_service.process_monthly_renewal(db)
    return RenewalOut(renewed_accounts=count)
