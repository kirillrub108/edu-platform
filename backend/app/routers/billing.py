import uuid
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    AUTO_CHARS_PER_SLIDE,
    CREDIT_PACKAGES,
    CREDIT_WEIGHTS,
    PAYMENT_TASK_PRIORITY,
    PLAN_CONFIGS,
    TTS_CHARS_PER_CREDIT,
    VIDEO_AUTO_BASE_CREDITS,
    VIDEO_TEXT_BASE_CREDITS,
    YOOKASSA_HANDLED_EVENTS,
)
from app.database import get_db
from app.dependencies import get_current_user, require_admin, require_verified_email
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
from app.services.webhook_security import is_trusted_yookassa_ip, resolve_client_ip
from app.tasks.payment_pipeline import process_yookassa_payment

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
    user: User = Depends(require_verified_email),
    db: AsyncSession = Depends(get_db),
):
    # The request carries ONLY package_key — price and credits are taken from
    # the server-side catalogue, never from the client.
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

    title = str(package.get("title") or f"{package['credits']} кредитов")
    try:
        yk = await yookassa_service.create_payment(
            amount_rub=f"{package['price_rub']:.2f}",
            description=f"Edllm: {title}",
            idempotence_key=payment.idempotence_key,
            metadata={
                "payment_id": str(payment.id),
                "user_id": str(user.id),
                "package_key": data.package_key,
            },
            title=title,
            vat_code=int(package.get("vat_code", settings.YOOKASSA_VAT_CODE)),
            payment_subject=str(package.get("payment_subject", "service")),
            payment_mode=str(package.get("payment_mode", "full_payment")),
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
    if yk.status == "succeeded":
        # Credit only when the authoritative amount/currency/paid match the
        # package — same anti-fraud gate as the webhook task.
        if yookassa_service.payment_matches(yk, payment.amount_rub):
            await billing_service.apply_purchase(db, payment.id)
        else:
            logger.error(
                "payment_amount_mismatch",
                payment_id=str(payment.id),
                expected=str(payment.amount_rub),
                got=(yk.amount.value if yk.amount else None),
            )
    elif yk.status == "canceled":
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
async def yookassa_webhook(request: Request):
    """YooKassa HTTP notification. The body is NEVER trusted: it only routes the
    event and points at a payment id, which the Celery task re-fetches from the
    YooKassa API and settles. The request is rejected (400) if its real client
    IP is outside the YooKassa ranges or the body is unparseable; every accepted
    or merely unknown event returns 200 immediately (heavy work runs in
    process_yookassa_payment) so YooKassa stops its 24h retries. No cookie-auth
    dependency → the route sits outside the CSRF double-submit check.
    """
    if settings.YOOKASSA_VERIFY_WEBHOOK_IP:
        ip = resolve_client_ip(request)
        if not is_trusted_yookassa_ip(ip):
            logger.warning("yookassa_webhook_untrusted_ip", ip=ip)
            raise HTTPException(status_code=400, detail="Untrusted source")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = (body or {}).get("event")
    obj = (body or {}).get("object") or {}
    if event not in YOOKASSA_HANDLED_EVENTS:
        logger.info("yookassa_webhook_ignored_event", event_type=event)
        return {"ok": True}

    # For refunds the object IS the refund (its payment_id points at the
    # payment); for payment.* events the object IS the payment.
    yk_payment_id = obj.get("payment_id") if event == "refund.succeeded" else obj.get("id")
    if not yk_payment_id or not isinstance(yk_payment_id, str):
        logger.warning("yookassa_webhook_missing_id", event_type=event)
        return {"ok": True}

    process_yookassa_payment.apply_async(
        args=[event, yk_payment_id],
        queue="quiz",
        priority=PAYMENT_TASK_PRIORITY,
    )
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
