"""Metering of the AI grading of open answers.

Free monthly allowance per teacher → credits past it → silent fallback to manual
review. These need a real PostgreSQL (the allowance is an atomic UPSERT and the
holds are row-locked), so they run against the testcontainer on a psycopg2
session mirroring the Celery worker rather than the SAVEPOINT-bound async one.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Iterator

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.models.credit import CreditAccount, CreditOperation, CreditPlan, CreditTransaction
from app.models.user import User, UserRole
from app.services.auth_service import hash_password
from app.services.quota_service import AI_GRADING, sync_try_consume_slot, utc_month_key

pytestmark = pytest.mark.integration


@pytest.fixture()
def sync_session(_alembic_upgraded: None) -> Iterator[Session]:
    """psycopg2 session mirroring the Celery worker; truncates tables after."""
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    sess = SessionLocal()
    try:
        yield sess
    finally:
        sess.close()
        with engine.connect() as conn:
            conn.execute(
                text(
                    "TRUNCATE TABLE usage_counters, credit_transactions, credit_accounts, "
                    "users RESTART IDENTITY CASCADE"
                )
            )
            conn.commit()
        engine.dispose()


def _make_teacher(session: Session, *, balance: int = 0) -> User:
    user = User(
        email=f"t-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password=hash_password("password123"),
        role=UserRole.teacher,
        is_active=True,
    )
    session.add(user)
    session.commit()
    session.add(CreditAccount(owner_id=user.id, plan=CreditPlan.free, balance=balance, reserved=0))
    session.commit()
    return user


# ── Atomicity of the monthly allowance ───────────────────────────────────────


def test_concurrent_consumers_never_oversell_the_monthly_allowance(
    sync_session: Session,
) -> None:
    """The allowance is one conditional UPSERT, so N racing workers grading
    different students' attempts against the SAME teacher counter can grant at
    most `limit` slots in total — never limit+1."""
    user_id = _make_teacher(sync_session).id
    limit = 10
    attempts = 40
    period = utc_month_key()

    # A separate pool-backed engine: each thread needs its own connection, and a
    # psycopg2 Session is not thread-safe. Mirrors the real topology (separate
    # worker processes, each on its own connection).
    url = os.environ["DATABASE_URL"].replace("+asyncpg", "+psycopg2")
    engine = create_engine(url, pool_pre_ping=True, pool_size=16, max_overflow=16)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def _consume(_i: int) -> bool:
        session = SessionLocal()
        try:
            return sync_try_consume_slot(session, user_id, AI_GRADING, limit, period)
        finally:
            session.close()

    try:
        with ThreadPoolExecutor(max_workers=16) as pool:
            granted = sum(pool.map(_consume, range(attempts)))
    finally:
        engine.dispose()

    sync_session.expire_all()
    stored = sync_session.scalar(
        text(
            "SELECT count FROM usage_counters WHERE user_id = :uid "
            "AND resource = :res AND period_key = :pk"
        ),
        {"uid": user_id, "res": AI_GRADING, "pk": period},
    )

    assert granted == limit, f"granted {granted} slots for a limit of {limit}"
    assert stored == limit, f"counter drifted to {stored}, expected {limit}"


def test_allowance_is_scoped_per_month(sync_session: Session) -> None:
    """A new calendar month yields a fresh counter — the period is in the key."""
    user = _make_teacher(sync_session)
    assert sync_try_consume_slot(sync_session, user.id, AI_GRADING, 1, "2026-08") is True
    assert sync_try_consume_slot(sync_session, user.id, AI_GRADING, 1, "2026-08") is False
    assert sync_try_consume_slot(sync_session, user.id, AI_GRADING, 1, "2026-09") is True


# ── Degradation: exhausted allowance + empty balance ─────────────────────────


def test_exhausted_allowance_and_zero_balance_defers_every_answer(
    sync_session: Session,
) -> None:
    """No slots, no credits → every answer is deferred to manual review and the
    ledger stays untouched. This is the "silent degradation" contract."""
    from app.tasks.quiz_pipeline import _authorize_grading

    user = _make_teacher(sync_session, balance=0)
    # Burn the whole monthly allowance first.
    period = utc_month_key()
    sync_session.execute(
        text(
            "INSERT INTO usage_counters (id, user_id, period_key, resource, count) "
            "VALUES (gen_random_uuid(), :uid, :pk, :res, 999999)"
        ),
        {"uid": user.id, "pk": period, "res": AI_GRADING},
    )
    sync_session.commit()

    answer_ids = [uuid.uuid4() for _ in range(3)]
    grants, deferred = _authorize_grading(sync_session, user.id, answer_ids)

    assert grants == {}
    assert set(deferred) == set(answer_ids)

    holds = sync_session.scalars(
        select(CreditTransaction).where(CreditTransaction.operation == CreditOperation.RESERVE)
    ).all()
    assert holds == []


def test_answers_within_the_allowance_are_free(sync_session: Session) -> None:
    user = _make_teacher(sync_session, balance=0)
    answer_ids = [uuid.uuid4() for _ in range(2)]

    from app.tasks.quiz_pipeline import _authorize_grading

    grants, deferred = _authorize_grading(sync_session, user.id, answer_ids)

    assert deferred == []
    # A None billing_ref means "covered by the allowance, nothing to settle".
    assert set(grants) == set(answer_ids)
    assert all(ref is None for ref in grants.values())

    holds = sync_session.scalars(
        select(CreditTransaction).where(CreditTransaction.operation == CreditOperation.RESERVE)
    ).all()
    assert holds == []


def test_overage_reserves_credits_then_settles_as_a_charge(sync_session: Session) -> None:
    """Past the allowance the answer is paid for: RESERVE up front, converted to
    a QUIZ_GRADE charge once the LLM actually graded it."""
    from app.constants import CREDIT_WEIGHTS
    from app.tasks.quiz_pipeline import _authorize_grading, _settle_grading

    cost = CREDIT_WEIGHTS["quiz_grade_overage"]
    user = _make_teacher(sync_session, balance=cost * 5)
    sync_session.execute(
        text(
            "INSERT INTO usage_counters (id, user_id, period_key, resource, count) "
            "VALUES (gen_random_uuid(), :uid, :pk, :res, 999999)"
        ),
        {"uid": user.id, "pk": utc_month_key(), "res": AI_GRADING},
    )
    sync_session.commit()

    answer_id = uuid.uuid4()
    grants, deferred = _authorize_grading(sync_session, user.id, [answer_id])
    assert deferred == []
    billing_ref = grants[answer_id]
    assert billing_ref is not None

    account = sync_session.scalar(select(CreditAccount).where(CreditAccount.owner_id == user.id))
    sync_session.refresh(account)
    assert account.reserved == cost, "hold must be visible before the LLM call"

    _settle_grading(sync_session, user.id, billing_ref, success=True)

    sync_session.refresh(account)
    assert account.reserved == 0
    assert account.balance == cost * 5 - cost

    ops = sync_session.scalars(
        select(CreditTransaction.operation).where(CreditTransaction.ref_id == billing_ref)
    ).all()
    assert CreditOperation.QUIZ_GRADE in ops


def test_failed_grading_releases_the_hold_without_charging(sync_session: Session) -> None:
    from app.constants import CREDIT_WEIGHTS
    from app.tasks.quiz_pipeline import _authorize_grading, _settle_grading

    cost = CREDIT_WEIGHTS["quiz_grade_overage"]
    start = cost * 5
    user = _make_teacher(sync_session, balance=start)
    sync_session.execute(
        text(
            "INSERT INTO usage_counters (id, user_id, period_key, resource, count) "
            "VALUES (gen_random_uuid(), :uid, :pk, :res, 999999)"
        ),
        {"uid": user.id, "pk": utc_month_key(), "res": AI_GRADING},
    )
    sync_session.commit()

    answer_id = uuid.uuid4()
    grants, _deferred = _authorize_grading(sync_session, user.id, [answer_id])
    _settle_grading(sync_session, user.id, grants[answer_id], success=False)

    account = sync_session.scalar(select(CreditAccount).where(CreditAccount.owner_id == user.id))
    sync_session.refresh(account)
    assert account.reserved == 0
    assert account.balance == start, "an LLM failure must not cost the teacher"


def test_partial_budget_grants_some_and_defers_the_rest(sync_session: Session) -> None:
    """The headline edge case: the allowance runs out mid-attempt and the balance
    only covers part of what is left. Some answers get graded, the rest fall back
    to manual review — the task never fails."""
    from app.constants import CREDIT_WEIGHTS
    from app.tasks.quiz_pipeline import _authorize_grading

    assert _authorize_grading is not None  # imported for symmetry with the helper
    cost = CREDIT_WEIGHTS["quiz_grade_overage"]
    free_slots = 2
    payable = 3
    deferrals = 2
    user = _make_teacher(sync_session, balance=cost * payable)

    answer_ids = [uuid.uuid4() for _ in range(free_slots + payable + deferrals)]
    grants, deferred = _authorize_grading_with_limit(sync_session, user.id, answer_ids, free_slots)

    assert len(grants) == free_slots + payable
    assert len(deferred) == deferrals
    assert sum(1 for ref in grants.values() if ref is None) == free_slots
    assert sum(1 for ref in grants.values() if ref is not None) == payable


def _authorize_grading_with_limit(
    session: Session, owner_id: uuid.UUID, answer_ids: list, limit: int
) -> tuple[dict, list]:
    """_authorize_grading with the allowance pinned, so the test does not depend
    on the production AI_GRADING_FREE_ANSWERS_PER_MONTH value."""
    import app.tasks.quiz_pipeline as qp

    original = qp.AI_GRADING_FREE_ANSWERS_PER_MONTH
    qp.AI_GRADING_FREE_ANSWERS_PER_MONTH = limit
    try:
        return qp._authorize_grading(session, owner_id, answer_ids)
    finally:
        qp.AI_GRADING_FREE_ANSWERS_PER_MONTH = original
