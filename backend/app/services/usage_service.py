"""generation_usage journal: actual provider spend per AI call (margin control).

Recording must work from every execution context the AI services run in —
FastAPI's event loop, Celery prefork workers, and their internal thread pools —
so the writer is a plain sync function on a private lazily-built psycopg2
engine (NullPool: calls are rare and short-lived, no pool to leak across
prefork forks). Async call sites use `arecord_*` (asyncio.to_thread) to keep
the event loop unblocked. A journal failure must never break the AI call:
every error is logged and swallowed.

Call context (operation / lesson_id / quiz_id) travels via a ContextVar set by
routers and tasks. contextvars survive asyncio.run(); thread-pool workers do
NOT inherit them, so threaded call sites (TTS pool, quiz grading pool) set the
context inside the thread function.
"""
import asyncio
from contextvars import ContextVar
from decimal import Decimal
from typing import Any
from uuid import UUID

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.constants import (
    LLM_RUB_PER_MTOK_COMPLETION,
    LLM_RUB_PER_MTOK_PROMPT,
    TTS_RUB_PER_MCHAR,
)
from app.models.generation_usage import GenerationUsage

logger = structlog.get_logger()

_usage_ctx: ContextVar[dict[str, Any] | None] = ContextVar("usage_ctx", default=None)

_engine = None
_SyncSession = None


def set_usage_context(
    operation: str,
    lesson_id: "UUID | str | None" = None,
    quiz_id: "UUID | str | None" = None,
) -> None:
    _usage_ctx.set(
        {
            "operation": operation,
            "lesson_id": UUID(str(lesson_id)) if lesson_id else None,
            "quiz_id": UUID(str(quiz_id)) if quiz_id else None,
        }
    )


def _get_session_factory():
    global _engine, _SyncSession
    if _SyncSession is None:
        # Late settings lookup via the module attribute: the test conftest
        # replaces app.config.settings after import, and this must pick up
        # the rebound testcontainer URL.
        from app import config

        _engine = create_engine(
            config.settings.DATABASE_URL.replace("+asyncpg", "+psycopg2"),
            poolclass=NullPool,
        )
        _SyncSession = sessionmaker(bind=_engine, expire_on_commit=False)
    return _SyncSession


def _llm_cost_rub(prompt_tokens: int | None, completion_tokens: int | None) -> Decimal:
    cost = (
        (prompt_tokens or 0) * LLM_RUB_PER_MTOK_PROMPT
        + (completion_tokens or 0) * LLM_RUB_PER_MTOK_COMPLETION
    ) / 1_000_000
    return Decimal(str(round(cost, 4)))


def _record(
    *,
    model: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    chars: int | None = None,
    cost_rub: Decimal,
) -> None:
    ctx = _usage_ctx.get() or {}
    try:
        factory = _get_session_factory()
        with factory() as session:
            session.add(
                GenerationUsage(
                    operation=ctx.get("operation") or "unknown",
                    model=model[:128],
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    chars=chars,
                    cost_rub=cost_rub,
                    lesson_id=ctx.get("lesson_id"),
                    quiz_id=ctx.get("quiz_id"),
                )
            )
            session.commit()
    except Exception:
        logger.warning("generation_usage_record_failed", model=model, exc_info=True)


def record_llm_usage(model: str, usage: Any) -> None:
    """Journal one chat-completion call. `usage` is the SDK usage object, a
    dict (Yandex raw JSON), or None (stubbed clients in tests → skipped)."""
    if usage is None:
        return
    if isinstance(usage, dict):
        prompt = usage.get("prompt_tokens")
        completion = usage.get("completion_tokens")
    else:
        prompt = getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "completion_tokens", None)
    if prompt is None and completion is None:
        return
    _record(
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        cost_rub=_llm_cost_rub(prompt, completion),
    )


async def arecord_llm_usage(model: str, usage: Any) -> None:
    if usage is None:
        return
    await asyncio.to_thread(record_llm_usage, model, usage)


def record_tts_usage(model: str, chars: int, billable: bool = True) -> None:
    """Journal one TTS synthesis (chars actually sent to the provider).
    billable=False for self-hosted providers (Silero) — chars logged, cost 0."""
    if chars <= 0:
        return
    cost = (
        Decimal(str(round(chars * TTS_RUB_PER_MCHAR / 1_000_000, 4)))
        if billable
        else Decimal("0")
    )
    _record(model=model, chars=chars, cost_rub=cost)


class UsageCostCollector:
    """Prometheus collector for AI cost: ai_cost_rub_total{operation}.

    Backed by a GROUP BY over generation_usage at scrape time, because the AI
    calls run in Celery worker processes whose in-process counters are never
    scraped (prometheus.yml only targets the backend). The table is
    append-only, so the series is monotonic (counter semantics).
    """

    def collect(self):  # pragma: no cover - exercised via /metrics
        from prometheus_client.core import CounterMetricFamily
        from sqlalchemy import func as sa_func
        from sqlalchemy import select

        family = CounterMetricFamily(
            "ai_cost_rub",
            "Cumulative AI provider cost in rubles from generation_usage",
            labels=["operation"],
        )
        try:
            factory = _get_session_factory()
            with factory() as session:
                rows = session.execute(
                    select(
                        GenerationUsage.operation,
                        sa_func.sum(GenerationUsage.cost_rub),
                    ).group_by(GenerationUsage.operation)
                ).all()
            for operation, total in rows:
                family.add_metric([operation], float(total or 0))
        except Exception:
            logger.warning("usage_cost_collector_failed", exc_info=True)
        yield family
