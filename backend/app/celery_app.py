import logging
import os

import sentry_sdk
from celery import Celery
from kombu import Queue
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.config import settings

logger = logging.getLogger(__name__)


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
            "Sentry initialized: environment=%s release=%s",
            settings.ENVIRONMENT,
            settings.APP_VERSION,
        )
        return True
    except Exception:
        logger.warning("Sentry initialization failed", exc_info=True)
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
    ),
    task_default_queue="video",
    task_default_routing_key="video",
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
)
