import logging
import os
import time

import sentry_sdk
import structlog
from celery import Celery
from celery.schedules import crontab
from kombu import Queue
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.config import settings
from app.logging_config import configure_logging

configure_logging(settings.ENVIRONMENT)

logger = structlog.get_logger()


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


def _init_sentry() -> bool:
    if not settings.SENTRY_DSN:
        return False
    try:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.ENVIRONMENT,
            release=settings.APP_VERSION,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            integrations=[
                CeleryIntegration(),
                SqlalchemyIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
        )
        logger.info(
            "sentry_initialized",
            environment=settings.ENVIRONMENT,
            release=settings.APP_VERSION,
        )
        return True
    except Exception:
        logger.warning("sentry_init_failed", exc_info=True)
        return False


_init_sentry()


celery_app = Celery(
    "edllm",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "app.tasks.video_pipeline",
        "app.tasks.vision_pipeline",
        "app.tasks.quiz_pipeline",
        "app.tasks.purge_pipeline",
        "app.tasks.email_pipeline",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=60 * 30,
    task_queues=(
        Queue("video", routing_key="video"),
        Queue("vision", routing_key="vision"),
        Queue("quiz", routing_key="quiz"),
        Queue("celery_email", routing_key="celery_email"),
    ),
    task_default_queue="video",
    task_default_routing_key="video",
    # ── Tier priority on the Redis broker ────────────────────────────────────
    # Redis has no native priorities; kombu fans each queue out into per-priority
    # sub-queues ("video", "video:1", … "video:9") and the worker drains the
    # LOWER number first — so 0 = highest priority, 9 = lowest (the REVERSE of
    # RabbitMQ). `queue_order_strategy='priority'` is what makes apply_async's
    # priority kwarg take effect; without it the value is ignored. priority_steps
    # is the set of valid buckets — TIER_PRIORITY values must fall inside it.
    broker_transport_options={
        "priority_steps": list(range(10)),
        "sep": ":",
        "queue_order_strategy": "priority",
    },
    # On prefork a worker prefetching >1 message can grab a low-priority task
    # before a later high-priority one is even seen, defeating prioritization.
    # Pin to 1 so each child holds exactly one unacked task at a time. Works with
    # task_acks_late (already set) so an unfinished task is re-queued on crash.
    worker_prefetch_multiplier=1,
    # Test-only knobs: when set to "1" in pytest, .delay()/.apply_async()
    # run synchronously in-process. Defaults to off, so production is
    # untouched.
    task_always_eager=_env_bool("CELERY_TASK_ALWAYS_EAGER"),
    task_eager_propagates=_env_bool("CELERY_TASK_EAGER_PROPAGATES"),
    # With Redis as broker the unacked message is held in-memory by the worker
    # until the task finishes (or the worker dies). On worker loss the broker
    # re-queues the message automatically, so the task is retried rather than
    # silently dropped.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Daily soft-delete purge. Routed to the `quiz` queue → handled by the
    # celery_quiz worker. A beat scheduler must be running (the celery_quiz
    # worker is started with --beat in docker-compose) for this to fire.
    beat_schedule={
        "purge-soft-deleted-daily": {
            "task": "purge_soft_deleted",
            "schedule": crontab(hour=3, minute=0),
            "options": {"queue": "quiz"},
        },
    },
)

if settings.METRICS_ENABLED:
    from celery.signals import task_failure, task_postrun, task_prerun
    from prometheus_client import Counter, Histogram

    _task_total = Counter(
        "celery_tasks_total",
        "Total Celery task executions",
        ["task_name", "status"],
    )
    _task_duration = Histogram(
        "celery_task_duration_seconds",
        "Celery task execution duration in seconds",
        ["task_name"],
    )
    _task_start: dict[str, float] = {}

    @task_prerun.connect
    def _on_task_prerun(task_id: str, task, **kwargs: object) -> None:
        _task_start[task_id] = time.perf_counter()

    @task_postrun.connect
    def _on_task_postrun(task_id: str, task, **kwargs: object) -> None:
        start = _task_start.pop(task_id, None)
        if start is not None:
            _task_duration.labels(task_name=task.name).observe(time.perf_counter() - start)
        _task_total.labels(task_name=task.name, status="success").inc()

    @task_failure.connect
    def _on_task_failure(task_id: str, sender, **kwargs: object) -> None:
        start = _task_start.pop(task_id, None)
        if start is not None:
            _task_duration.labels(task_name=sender.name).observe(time.perf_counter() - start)
        _task_total.labels(task_name=sender.name, status="failure").inc()
