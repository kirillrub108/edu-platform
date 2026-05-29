"""Credit billing: balances, reservations, charges and monthly renewals.

Async functions are used from FastAPI routers (AsyncSession). Celery tasks run
on a sync Session (psycopg2) and must use the `sync_*` wrappers — never import
the async functions into `app/tasks/*`.

Reservation lifecycle (auth/capture style):
  reserve_credits → hold moves into `reserved`, `available` drops.
  charge_credits  → on success: balance -= amount, reserved -= amount.
  release_credits → on failure: reserved -= amount, balance untouched.
"""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.constants import CREDIT_CARRYOVER_RATIO, PLAN_CONFIGS
from app.models.credit import CreditAccount, CreditOperation, CreditPlan, CreditTransaction

_RENEWAL_PERIOD = timedelta(days=30)


def _to_operation(operation: "str | CreditOperation") -> CreditOperation:
    return operation if isinstance(operation, CreditOperation) else CreditOperation(operation)


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


def _sync_get_or_create_account(db: Session, user_id: UUID) -> CreditAccount:
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
    new_id = db.execute(stmt).scalar_one_or_none()
    if new_id is not None and free["onetime_credits"]:
        db.add(
            CreditTransaction(
                account_id=new_id,
                delta=free["onetime_credits"],
                operation=CreditOperation.GRANT,
                description="Welcome credits (free plan)",
            )
        )
    db.commit()
    return db.scalar(select(CreditAccount).where(CreditAccount.owner_id == user_id))


def sync_reserve_credits(
    db: Session, user_id: UUID, amount: int, ref_id: str, operation: str
) -> bool:
    _sync_get_or_create_account(db, user_id)
    account = db.scalar(
        select(CreditAccount).where(CreditAccount.owner_id == user_id).with_for_update()
    )
    if account is None or account.balance - account.reserved < amount:
        db.rollback()
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
    db.commit()
    return True


def sync_release_credits(db: Session, user_id: UUID, amount: int, ref_id: str) -> None:
    account = db.scalar(
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
    db.commit()


def sync_charge_credits(
    db: Session, user_id: UUID, amount: int, ref_id: str, operation: str
) -> None:
    op = _to_operation(operation)
    account = db.scalar(
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
    db.commit()
