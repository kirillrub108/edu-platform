import os

from celery import Celery
from kombu import Queue

from app.config import settings


def _env_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


celery_app = Celery(
    "edu_platform",
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
