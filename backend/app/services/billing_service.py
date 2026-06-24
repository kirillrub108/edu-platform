"""Credit billing: balances, reservations, charges, purchases and renewals.

Async functions are used from FastAPI routers (AsyncSession). Celery tasks run
on a sync Session (psycopg2) and must use the `sync_*` wrappers — never import
the async functions into `app/tasks/*`.

Reservation lifecycle (auth/capture style). The full generation estimate is
reserved router-side before apply_async (ref_id = the per-launch billing_ref);
the task settles it exactly once via the idempotent finalizer:
  reserve_credits           → hold moves into `reserved`, `available` drops.
  sync_finalize_generation  → success: charge the full estimate; failure:
                              release 100%; mid-run cancel: charge the partial
                              cost and release the remainder — one transaction,
                              a no-op if billing_ref already has a finalizer
                              row (Celery redelivery / cancel races).
  release_reservation_if_held → cancel path for a task that never settled.
"""
import math
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.constants import (
    AUTO_CHARS_PER_SLIDE,
    CREDIT_CARRYOVER_RATIO,
    PLAN_CONFIGS,
    TTS_CHARS_PER_CREDIT,
    VIDEO_AUTO_BASE_CREDITS,
    VIDEO_TEXT_BASE_CREDITS,
)
from app.models.credit import CreditAccount, CreditOperation, CreditPlan, CreditTransaction
from app.models.lesson import Lesson
from app.models.payment import Payment, PaymentStatus

_RENEWAL_PERIOD = timedelta(days=30)


def _to_operation(operation: "str | CreditOperation") -> CreditOperation:
    return operation if isinstance(operation, CreditOperation) else CreditOperation(operation)


# ── Pricing formulas (pure — safe to import anywhere, including tasks) ────────


def estimate_video_text(slides: int, script_chars: int) -> int:
    """COST_VIDEO_TEXT: 2 + slides + ceil(script_chars / 3000)."""
    return (
        VIDEO_TEXT_BASE_CREDITS
        + slides
        + math.ceil(script_chars / TTS_CHARS_PER_CREDIT)
    )


def estimate_video_auto(slides: int) -> int:
    """COST_VIDEO_AUTO: 3 + slides + ceil(slides * 600 / 3000)."""
    return (
        VIDEO_AUTO_BASE_CREDITS
        + slides
        + math.ceil(slides * AUTO_CHARS_PER_SLIDE / TTS_CHARS_PER_CREDIT)
    )


def partial_video_cost(base_credits: int, processed_slides: int, voiced_chars: int) -> int:
    """Mid-run cancellation price: base + per-slide × processed + voiced chars
    rounded UP to whole credits. Callers clamp to the reserved estimate."""
    return (
        base_credits
        + processed_slides
        + math.ceil(voiced_chars / TTS_CHARS_PER_CREDIT)
    )


def partial_vision_cost(total_cost: int, done: int, total: int) -> int:
    """Pro-rata vision-analysis cancellation price, rounded up per slide."""
    if total <= 0:
        return 0
    return min(total_cost, math.ceil(total_cost * done / total))


# ── Async (FastAPI) ──────────────────────────────────────────────────────────


async def get_or_create_account(db: AsyncSession, user_id: UUID) -> CreditAccount:
    """Race-safe upsert: INSERT ... ON CONFLICT DO NOTHING, then SELECT.

    A freshly created account starts on the free plan with its one-time credits
    and a matching GRANT transaction for the audit trail.
    """
    free = PLAN_CONFIGS["free"]
    stmt = (
        pg_insert(CreditAccount)
        .values(
            owner_id=user_id,
            plan=CreditPlan.free,
            balance=free["onetime_credits"],
            reserved=0,
            monthly_allowance=free["monthly_allowance"],
        )
        .on_conflict_do_nothing(index_elements=["owner_id"])
        .returning(CreditAccount.id)
    )
    new_id = (await db.execute(stmt)).scalar_one_or_none()
    if new_id is not None and free["onetime_credits"]:
        db.add(
            CreditTransaction(
                account_id=new_id,
                delta=free["onetime_credits"],
                operation=CreditOperation.GRANT,
                description="Welcome credits (free plan)",
            )
        )
    await db.commit()
    return await db.scalar(select(CreditAccount).where(CreditAccount.owner_id == user_id))


async def get_balance(db: AsyncSession, user_id: UUID) -> dict:
    account = await get_or_create_account(db, user_id)
    return {
        "balance": account.balance,
        "reserved": account.reserved,
        "available": account.balance - account.reserved,
        "plan": account.plan.value,
    }


async def reserve_credits(
    db: AsyncSession,
    user_id: UUID,
    amount: int,
    ref_id: str,
    operation: CreditOperation,
) -> bool:
    """Atomically hold `amount` credits if available. Returns False (no raise)
    when the account cannot cover the amount."""
    await get_or_create_account(db, user_id)
    account = await db.scalar(
        select(CreditAccount).where(CreditAccount.owner_id == user_id).with_for_update()
    )
    if account.balance - account.reserved < amount:
        await db.rollback()
        return False
    account.reserved += amount
    db.add(
        CreditTransaction(
            account_id=account.id,
            delta=-amount,
            operation=CreditOperation.RESERVE,
            ref_id=ref_id,
            description=f"Reserve for {_to_operation(operation).value}",
        )
    )
    await db.commit()
    return True


async def release_credits(db: AsyncSession, user_id: UUID, amount: int, ref_id: str) -> None:
    """Return a previously reserved hold without touching the balance."""
    account = await db.scalar(
        select(CreditAccount).where(CreditAccount.owner_id == user_id).with_for_update()
    )
    if account is None:
        return
    account.reserved = max(0, account.reserved - amount)
    db.add(
        CreditTransaction(
            account_id=account.id,
            delta=amount,
            operation=CreditOperation.RELEASE,
            ref_id=ref_id,
            description="Release reserved hold",
        )
    )
    await db.commit()


async def release_reservation_if_held(db: AsyncSession, user_id: UUID, ref_id: str) -> bool:
    """Idempotently release an outstanding hold identified by `ref_id`.

    The cancel endpoints kill the Celery task with terminate=True, so the task's
    `finally` block (which charges or releases the reservation) is not guaranteed
    to run — the reserved hold would leak. This releases that hold, but only when
    a RESERVE for `ref_id` has not already been finalized (charged or released),
    so it is a safe no-op if the task happened to finish before the revoke landed.

    The account row is locked for the whole check-then-release so a concurrent
    `charge_credits`/`release_credits` from the task's `finally` cannot double-free
    the hold. The released amount is read back from the outstanding RESERVE row, so
    it matches exactly what was held. Returns True when a release was performed.
    """
    account = await db.scalar(
        select(CreditAccount).where(CreditAccount.owner_id == user_id).with_for_update()
    )
    if account is None:
        return False

    reserved_count = await db.scalar(
        select(func.count())
        .select_from(CreditTransaction)
        .where(
            CreditTransaction.account_id == account.id,
            CreditTransaction.ref_id == ref_id,
            CreditTransaction.operation == CreditOperation.RESERVE,
        )
    )
    # For a task ref_id the only non-RESERVE rows are its finalizers (RELEASE or a
    # charge op); GRANT/TOPUP/EXPIRE never carry a task ref_id.
    finalized_count = await db.scalar(
        select(func.count())
        .select_from(CreditTransaction)
        .where(
            CreditTransaction.account_id == account.id,
            CreditTransaction.ref_id == ref_id,
            CreditTransaction.operation != CreditOperation.RESERVE,
        )
    )
    if (reserved_count or 0) <= (finalized_count or 0):
        # Nothing outstanding. The FOR UPDATE lock is dropped when the request's
        # session is committed/closed right after this returns.
        return False

    last_reserve = await db.scalar(
        select(CreditTransaction)
        .where(
            CreditTransaction.account_id == account.id,
            CreditTransaction.ref_id == ref_id,
            CreditTransaction.operation == CreditOperation.RESERVE,
        )
        .order_by(CreditTransaction.created_at.desc())
        .limit(1)
    )
    amount = -last_reserve.delta
    account.reserved = max(0, account.reserved - amount)
    db.add(
        CreditTransaction(
            account_id=account.id,
            delta=amount,
            operation=CreditOperation.RELEASE,
            ref_id=ref_id,
            description="Release reserved hold (task cancelled)",
        )
    )
    await db.commit()
    return True


async def charge_credits(
    db: AsyncSession,
    user_id: UUID,
    amount: int,
    ref_id: str,
    operation: CreditOperation,
) -> None:
    """Finalize a reservation: debit the balance and free the hold."""
    op = _to_operation(operation)
    account = await db.scalar(
        select(CreditAccount).where(CreditAccount.owner_id == user_id).with_for_update()
    )
    if account is None:
        return
    account.balance = max(0, account.balance - amount)
    account.reserved = max(0, account.reserved - amount)
    db.add(
        CreditTransaction(
            account_id=account.id,
            delta=-amount,
            operation=op,
            ref_id=ref_id,
            description=f"Charge for {op.value}",
        )
    )
    await db.commit()


async def grant_credits(
    db: AsyncSession, user_id: UUID, amount: int, description: str
) -> CreditTransaction:
    """Credit the balance (admin grant / future payment gateway)."""
    account = await get_or_create_account(db, user_id)
    account = await db.scalar(
        select(CreditAccount).where(CreditAccount.id == account.id).with_for_update()
    )
    account.balance += amount
    tx = CreditTransaction(
        account_id=account.id,
        delta=amount,
        operation=CreditOperation.GRANT,
        description=description,
    )
    db.add(tx)
    await db.commit()
    await db.refresh(tx)
    return tx


async def claim_billing(db: AsyncSession, lesson_id: UUID) -> str | None:
    """Atomically claim the unsettled billing of a lesson's generation run.

    Returns the claimed billed_via ('credits' | 'trial') and nulls the column,
    or None when the run was already settled. The FOR UPDATE lock on the lesson
    row serializes the cancel endpoint against the task's finalizer so exactly
    one side performs the release/charge (critical for trial slots, which have
    no ledger rows to make them idempotent).
    """
    billed = await db.scalar(
        select(Lesson.billed_via).where(Lesson.id == lesson_id).with_for_update()
    )
    if billed is None:
        await db.rollback()
        return None
    await db.execute(update(Lesson).where(Lesson.id == lesson_id).values(billed_via=None))
    await db.commit()
    return billed


async def apply_purchase(db: AsyncSession, payment_id: UUID) -> bool:
    """Credit a succeeded YooKassa payment exactly once (one transaction).

    Locks the payment row first, then the account row (same lock order as the
    polling path, so webhook + poll cannot deadlock). Re-delivery of the same
    webhook finds status=succeeded and is a no-op. Returns True when credits
    were granted by this call.
    """
    # Ensure the account exists BEFORE taking any locks: get_or_create_account
    # commits, which would otherwise drop the payment FOR UPDATE lock mid-flow
    # and reopen the double-grant race this function exists to prevent.
    peek = await db.scalar(select(Payment).where(Payment.id == payment_id))
    if peek is None:
        return False
    await get_or_create_account(db, peek.user_id)

    payment = await db.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )
    if payment is None or payment.status == PaymentStatus.succeeded:
        await db.rollback()
        return False
    account = await db.scalar(
        select(CreditAccount)
        .where(CreditAccount.owner_id == payment.user_id)
        .with_for_update()
    )
    account.balance += payment.credits
    db.add(
        CreditTransaction(
            account_id=account.id,
            delta=payment.credits,
            operation=CreditOperation.PURCHASE,
            ref_id=str(payment.id),
            description=f"Покупка пакета {payment.credits} кредитов",
        )
    )
    payment.status = PaymentStatus.succeeded
    payment.paid_at = datetime.now(timezone.utc)
    await db.commit()
    return True


async def mark_payment_canceled(db: AsyncSession, payment_id: UUID) -> bool:
    """Mark a pending payment canceled; no-op for settled payments."""
    payment = await db.scalar(
        select(Payment).where(Payment.id == payment_id).with_for_update()
    )
    if payment is None or payment.status != PaymentStatus.pending:
        await db.rollback()
        return False
    payment.status = PaymentStatus.canceled
    await db.commit()
    return True


async def get_transaction_history(
    db: AsyncSession, user_id: UUID, limit: int = 50
) -> list[CreditTransaction]:
    account = await db.scalar(select(CreditAccount).where(CreditAccount.owner_id == user_id))
    if account is None:
        return []
    result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.account_id == account.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def process_monthly_renewal(db: AsyncSession) -> int:
    """Top up every non-free account whose allowance is due. Carries over up to
    CREDIT_CARRYOVER_RATIO of the monthly allowance; the rest expires."""
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(CreditAccount)
        .where(CreditAccount.plan != CreditPlan.free)
        .where(CreditAccount.allowance_resets_at <= now)
        .with_for_update()
    )
    accounts = list(result.scalars().all())
    for account in accounts:
        carry = min(account.balance, int(account.monthly_allowance * CREDIT_CARRYOVER_RATIO))
        expired = account.balance - carry
        if expired > 0:
            db.add(
                CreditTransaction(
                    account_id=account.id,
                    delta=-expired,
                    operation=CreditOperation.EXPIRE,
                    description="Unused credits expired at renewal",
                )
            )
        account.balance = carry + account.monthly_allowance
        account.allowance_resets_at = now + _RENEWAL_PERIOD
        db.add(
            CreditTransaction(
                account_id=account.id,
                delta=account.monthly_allowance,
                operation=CreditOperation.GRANT,
                description="Monthly allowance",
            )
        )
    await db.commit()
    return len(accounts)


# ── Sync wrappers (Celery) ─────────────────────────────────────────────────────


def sync_claim_billing(db: Session, lesson_id: UUID) -> str | None:
    """Sync mirror of claim_billing — see its docstring."""
    billed = db.scalar(
        select(Lesson.billed_via).where(Lesson.id == lesson_id).with_for_update()
    )
    if billed is None:
        db.rollback()
        return None
    db.execute(update(Lesson).where(Lesson.id == lesson_id).values(billed_via=None))
    db.commit()
    return billed


def sync_finalize_generation(
    db: Session,
    user_id: UUID,
    billing_ref: str,
    estimate: int,
    spent: int,
    operation: str,
) -> bool:
    """Settle a router-side reservation exactly once, in one transaction.

    spent == estimate → plain charge (success); spent == 0 → full release
    (service failure); 0 < spent < estimate → partial charge + release of the
    remainder (mid-run cancel). Idempotent: a second call for the same
    billing_ref (Celery redelivery after a worker crash, or a cancel-endpoint
    race) finds an existing finalizer row and does nothing. Returns True when
    this call performed the settlement.
    """
    op = _to_operation(operation)
    account = db.scalar(
        select(CreditAccount).where(CreditAccount.owner_id == user_id).with_for_update()
    )
    if account is None:
        db.rollback()
        return False
    finalized = db.scalar(
        select(func.count())
        .select_from(CreditTransaction)
        .where(
            CreditTransaction.account_id == account.id,
            CreditTransaction.ref_id == billing_ref,
            CreditTransaction.operation != CreditOperation.RESERVE,
        )
    )
    if finalized:
        db.rollback()
        return False

    spent = max(0, min(spent, estimate))
    remainder = estimate - spent
    account.reserved = max(0, account.reserved - estimate)
    account.balance = max(0, account.balance - spent)
    if spent:
        db.add(
            CreditTransaction(
                account_id=account.id,
                delta=-spent,
                operation=op,
                ref_id=billing_ref,
                description=f"Charge for {op.value}",
            )
        )
    if remainder or not spent:
        db.add(
            CreditTransaction(
                account_id=account.id,
                delta=remainder,
                operation=CreditOperation.RELEASE,
                ref_id=billing_ref,
                description=(
                    "Release reserved hold"
                    if not spent
                    else "Release remainder (partial charge)"
                ),
            )
        )
    db.commit()
    return True


def sync_apply_purchase(db: Session, payment: Payment, *, yookassa_payment_id: str) -> bool:
    """Credit a succeeded YooKassa payment exactly once, from the Celery task.

    Sync mirror of apply_purchase. The caller (process_yookassa_payment) has
    already locked `payment` FOR UPDATE in this transaction and validated the
    authoritative amount, so this just credits, flips status and stamps paid_at
    in one commit. A redelivery finds status != pending and is a no-op.
    """
    if payment.status != PaymentStatus.pending:
        db.rollback()
        return False
    free = PLAN_CONFIGS["free"]
    # Ensure the account exists WITHOUT committing — a commit here would drop the
    # payment FOR UPDATE lock and reopen the double-grant race. on_conflict_do_
    # nothing makes the insert a no-op when the account already exists.
    db.execute(
        pg_insert(CreditAccount)
        .values(
            owner_id=payment.user_id,
            plan=CreditPlan.free,
            balance=free["onetime_credits"],
            reserved=0,
            monthly_allowance=free["monthly_allowance"],
        )
        .on_conflict_do_nothing(index_elements=["owner_id"])
    )
    db.flush()
    account = db.scalar(
        select(CreditAccount).where(CreditAccount.owner_id == payment.user_id).with_for_update()
    )
    account.balance += payment.credits
    db.add(
        CreditTransaction(
            account_id=account.id,
            delta=payment.credits,
            operation=CreditOperation.PURCHASE,
            ref_id=str(payment.id),
            description=f"Покупка пакета {payment.credits} кредитов",
        )
    )
    if not payment.yookassa_payment_id:
        payment.yookassa_payment_id = yookassa_payment_id
    payment.status = PaymentStatus.succeeded
    payment.paid_at = datetime.now(timezone.utc)
    db.commit()
    return True


def sync_mark_payment_canceled(db: Session, payment: Payment) -> bool:
    """Sync mirror of mark_payment_canceled (used by the webhook task)."""
    if payment.status != PaymentStatus.pending:
        db.rollback()
        return False
    payment.status = PaymentStatus.canceled
    db.commit()
    return True


def sync_mark_payment_refunded(db: Session, payment: Payment) -> bool:
    """Record a refund.succeeded notification once. Spent credits are NOT clawed
    back automatically — that is a manual/finance decision (see docs/DECISIONS.md);
    we only stamp refunded_at for the audit trail."""
    if payment.refunded_at is not None:
        db.rollback()
        return False
    payment.refunded_at = datetime.now(timezone.utc)
    db.commit()
    return True
