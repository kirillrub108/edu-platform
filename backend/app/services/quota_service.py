"""Durable usage quotas backed by usage_counters (atomic UPSERT).

Today the only consumer is the lifetime free-account trial: period_key
'lifetime', resources 'trial_lecture' (2 slots) and 'trial_quiz' (2 slots).
A slot is consumed atomically before a generation launches and released when
the service (not the user) is at fault — task failure, or a cancel before the
first slide was processed.

Async functions are used from FastAPI routers (AsyncSession); Celery tasks use
the `sync_*` wrappers on their psycopg2 Session — never import the async
functions into `app/tasks/*`.
"""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.constants import TRIAL_LECTURES, TRIAL_QUIZZES
from app.models.usage_counter import UsageCounter

LIFETIME_PERIOD = "lifetime"
TRIAL_LECTURE = "trial_lecture"
TRIAL_QUIZ = "trial_quiz"

# Daily per-(student, quiz) cap on the free open-answer LLM grading. The day is
# encoded in period_key, the quiz in resource, so the unique key already scopes
# the counter per student/quiz/day.
GRADING_ATTEMPT_PREFIX = "grading_attempt:"


def grading_resource(quiz_id: UUID) -> str:
    """usage_counters.resource for a quiz's daily student-grading cap."""
    return f"{GRADING_ATTEMPT_PREFIX}{quiz_id}"


def utc_day_key(now: datetime | None = None) -> str:
    """Daily period_key (UTC) — a new calendar day yields a fresh counter."""
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")

TRIAL_LIMITS: dict[str, int] = {
    TRIAL_LECTURE: TRIAL_LECTURES,
    TRIAL_QUIZ: TRIAL_QUIZZES,
}


def _consume_stmt(user_id: UUID, resource: str, limit: int, period_key: str):
    """INSERT … ON CONFLICT DO UPDATE … WHERE count < :limit RETURNING count.

    The conditional DO UPDATE makes consumption atomic under concurrency: when
    the counter is already at the limit the WHERE clause suppresses the update
    and RETURNING yields no row → the slot is denied.
    """
    return (
        pg_insert(UsageCounter)
        .values(user_id=user_id, period_key=period_key, resource=resource, count=1)
        .on_conflict_do_update(
            constraint="uq_usage_counters_user_period_resource",
            set_={"count": UsageCounter.count + 1, "updated_at": func.now()},
            where=(UsageCounter.count < limit),
        )
        .returning(UsageCounter.count)
    )


def _release_stmt(user_id: UUID, resource: str, period_key: str):
    return (
        update(UsageCounter)
        .where(
            UsageCounter.user_id == user_id,
            UsageCounter.period_key == period_key,
            UsageCounter.resource == resource,
            UsageCounter.count > 0,
        )
        .values(count=UsageCounter.count - 1)
    )


# ── Async (FastAPI) ──────────────────────────────────────────────────────────


async def try_consume_slot(
    db: AsyncSession,
    user_id: UUID,
    resource: str,
    limit: int,
    period_key: str = LIFETIME_PERIOD,
) -> bool:
    """Atomically take one slot; False when the limit is exhausted."""
    if limit <= 0:
        return False
    taken = (
        await db.execute(_consume_stmt(user_id, resource, limit, period_key))
    ).scalar_one_or_none()
    await db.commit()
    return taken is not None


async def release_slot(
    db: AsyncSession, user_id: UUID, resource: str, period_key: str = LIFETIME_PERIOD
) -> None:
    """Return one slot (service-fault refund). Clamped at zero."""
    await db.execute(_release_stmt(user_id, resource, period_key))
    await db.commit()


async def get_usage(
    db: AsyncSession, user_id: UUID, resource: str, period_key: str = LIFETIME_PERIOD
) -> int:
    count = await db.scalar(
        select(UsageCounter.count).where(
            UsageCounter.user_id == user_id,
            UsageCounter.period_key == period_key,
            UsageCounter.resource == resource,
        )
    )
    return count or 0


async def get_trial_state(db: AsyncSession, user_id: UUID) -> dict:
    """Trial snapshot for the estimate endpoint / 402 payloads."""
    lectures_used = await get_usage(db, user_id, TRIAL_LECTURE)
    quizzes_used = await get_usage(db, user_id, TRIAL_QUIZ)
    return {
        "lectures_used": lectures_used,
        "lectures_limit": TRIAL_LECTURES,
        "quizzes_used": quizzes_used,
        "quizzes_limit": TRIAL_QUIZZES,
    }


# ── Sync wrappers (Celery) ────────────────────────────────────────────────────


def sync_release_slot(
    db: Session, user_id: UUID, resource: str, period_key: str = LIFETIME_PERIOD
) -> None:
    db.execute(_release_stmt(user_id, resource, period_key))
    db.commit()
