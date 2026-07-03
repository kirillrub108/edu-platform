import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager

import sentry_sdk
import structlog
from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.logging import LoggingIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import engine
from app.limiter import limiter
from app.logging_config import configure_logging
from app.redis_client import close_redis
from app.routers import (
    analytics,
    assignment_student,
    assignment_teacher,
    auth,
    billing,
    comments,
    courses,
    files,
    gradebook,
    lessons,
    quiz_student,
    quiz_teacher,
    slides,
    students,
    uploads,
)
from app.services import yookassa_service

logger = structlog.get_logger()


def _before_send(event: dict, hint: dict) -> dict | None:
    exc_info = hint.get("exc_info")
    if exc_info:
        exc = exc_info[1]
        if isinstance(exc, StarletteHTTPException) and exc.status_code < 500:
            return None
    return event


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
                FastApiIntegration(),
                SqlalchemyIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            before_send=_before_send,
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

if settings.ENVIRONMENT == "production" and not (settings.SENTRY_DSN or "").strip():
    logger.warning(
        "sentry_disabled_in_production",
        detail="SENTRY_DSN is empty — error monitoring is OFF. Set it in .env.prod.",
    )


def _reconcile_stuck_lessons() -> None:
    """Idempotent startup sweep: mark lessons stuck in a non-terminal status as error.

    A lesson is "stuck" when its status is analyzing or processing, a task_id is set
    (so a Celery task was dispatched), and updated_at is older than
    STUCK_LESSON_GRACE_MINUTES. The grace window must exceed the worst-case pipeline
    runtime so that legitimately in-flight tasks during a rolling restart are not
    disturbed — only truly orphaned tasks (Redis flushdb, crash without AOF) will have
    a stale updated_at.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import and_, create_engine, or_, select
    from sqlalchemy.orm import sessionmaker

    from app.constants import STUCK_LESSON_GRACE_MINUTES
    from app.models import Lesson, LessonStatus
    from app.tasks.video_pipeline import _set_status as _video_set_status
    from app.tasks.vision_pipeline import _set_status as _vision_set_status

    sync_url = settings.DATABASE_URL.replace("+asyncpg", "+psycopg2")
    engine = create_engine(sync_url, pool_size=1, max_overflow=0, pool_pre_ping=True)
    SyncSession = sessionmaker(bind=engine, expire_on_commit=False)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=STUCK_LESSON_GRACE_MINUTES)

    try:
        with SyncSession() as session:
            stuck: list[Lesson] = (
                session.execute(
                    select(Lesson).where(
                        or_(
                            and_(
                                Lesson.status == LessonStatus.analyzing,
                                Lesson.analyze_task_id.isnot(None),
                            ),
                            and_(
                                Lesson.status == LessonStatus.processing,
                                Lesson.video_task_id.isnot(None),
                            ),
                        ),
                        Lesson.updated_at < cutoff,
                    )
                )
                .scalars()
                .all()
            )
            for lesson in stuck:
                logger.warning(
                    "reconciling_stuck_lesson",
                    lesson_id=str(lesson.id),
                    status=lesson.status,
                    updated_at=lesson.updated_at.isoformat() if lesson.updated_at else None,
                )
                if lesson.status == LessonStatus.analyzing:
                    _vision_set_status(session, lesson.id, LessonStatus.error)
                else:
                    _video_set_status(session, lesson.id, LessonStatus.error)
            if stuck:
                logger.info("startup_reconciliation_complete", count=len(stuck))
    finally:
        engine.dispose()


async def _ensure_schema_at_head() -> None:
    """Run any pending Alembic migrations on startup so the schema always
    matches the latest revision in code. Replaces the old metadata.create_all
    bootstrap, which silently diverged from migration history and caused
    'type already exists' errors on first `alembic upgrade head`.
    """
    from alembic.config import Config

    from alembic import command

    cfg = Config("/app/alembic.ini")
    cfg.set_main_option("script_location", "/app/alembic")
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("+asyncpg", "+psycopg2"))

    def _upgrade() -> None:
        command.upgrade(cfg, "head")

    await asyncio.to_thread(_upgrade)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.ENVIRONMENT)

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("db_connection_ok")
    except Exception as exc:
        logger.error("db_connection_failed", error=str(exc))

    if settings.RUN_MIGRATIONS_ON_STARTUP:
        try:
            await _ensure_schema_at_head()
            logger.info("alembic_migrations_applied")
        except Exception:
            logger.exception("alembic_upgrade_failed")
            raise
    else:
        # Prod: migrations run as a separate one-shot deploy step before the
        # app rolls out (see docker-compose.prod.yml `migrate` service).
        logger.info("alembic_migrations_skipped_on_startup")

    try:
        await asyncio.to_thread(_reconcile_stuck_lessons)
    except Exception:
        logger.exception("startup_reconciliation_failed")

    # Build the shared YooKassa HTTP client up front so the first payment
    # request doesn't pay the construction cost.
    yookassa_service.get_client()

    yield
    await engine.dispose()
    await close_redis()
    await yookassa_service.close_client()


app = FastAPI(
    title="Edllm API",
    description="AI-platform for creating and delivering educational content",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter

# ── Prometheus ────────────────────────────────────────────────────────────────
# instrument() must be called before any add_middleware() so the Prometheus
# middleware sits innermost in the user stack.
# Final stack (outer → inner): CORS → request_id → log_and_catch → Prometheus
if settings.METRICS_ENABLED:
    from prometheus_fastapi_instrumentator import Instrumentator

    Instrumentator().instrument(app).expose(app)

    # AI provider cost (₽) from the generation_usage journal. DB-backed
    # collector because the AI calls run in Celery workers whose in-process
    # counters are never scraped (prometheus.yml targets only the backend).
    from prometheus_client import REGISTRY

    from app.services.usage_service import UsageCostCollector

    try:
        REGISTRY.register(UsageCostCollector())
    except ValueError:
        pass  # already registered (test re-imports)

# ── Middleware ────────────────────────────────────────────────────────────────
# In modern Starlette, `app.add_middleware()` *prepends* to user_middleware
# (insert(0, ...)), so the LAST middleware registered ends up OUTERMOST. We
# need this stack from outside in:
#
#     ServerErrorMiddleware   (built-in, always outermost)
#       → CORSMiddleware       ← MUST be outside log_and_catch so the 500
#         → request_id         ← binds request_id before log_and_catch sees it
#           → log_and_catch    ← JSONResponse it returns flows back through CORS
#             → Prometheus     ← measures actual route latency (innermost)
#               → ExceptionMiddleware
#                 → routes
#
# Therefore: register log_and_catch FIRST, then request_id, then CORS LAST.


@app.middleware("http")
async def log_and_catch(request: Request, call_next):
    """Access log + last-resort 500 handler. Sits inside request_id in the stack."""
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.error(
            "unhandled_error",
            method=request.method,
            path=request.url.path,
            status_code=500,
            elapsed_ms=round(elapsed_ms, 1),
            exc_type=type(exc).__name__,
            exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        elapsed_ms=round(elapsed_ms, 1),
    )
    return response


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    structlog.contextvars.clear_contextvars()
    request_id = uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(request_id=request_id)
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


def _assert_cors_allowlist_safe(cors_origins: list[str], environment: str) -> bool:
    """Return True if '*' is configured (forcing credentials off), else False.

    Auth runs on cookies, so allow_credentials=True with a wildcard origin is
    forbidden by the CORS spec — the code below already downgrades credentials
    to False when '*' is present. Here we make that downgrade loud (warn) and,
    in production, fatal: a wildcard would silently disable cookie auth
    cross-origin, so we fail fast instead of shipping it.
    """
    allow_all = "*" in cors_origins
    if allow_all:
        logger.warning(
            "cors_wildcard_origin",
            detail="CORS_ORIGINS contains '*'; cross-origin cookie credentials are disabled",
            environment=environment,
        )
        if environment == "production":
            raise RuntimeError(
                "CORS_ORIGINS must be an explicit allowlist in production; "
                "wildcard '*' disables cookie-based auth cross-origin"
            )
    return allow_all


_cors_origins = settings.CORS_ORIGINS
_allow_all = _assert_cors_allowlist_safe(_cors_origins, settings.ENVIRONMENT)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_all else _cors_origins,
    allow_credentials=False if _allow_all else True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,
)


# ── Exception handlers (HTTPException + validation) ──────────────────────────
# These types are caught by Starlette's ExceptionMiddleware, which is innermost
# in the stack — its responses already flow back through CORS, so headers are
# preserved without any extra effort. We override the defaults purely to
# guarantee a consistent JSON shape ({"detail": ...}).


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=exc.headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    # errors() may carry non-serializable objects in "ctx" (e.g. the ValueError a
    # model_validator raised) — jsonable_encoder stringifies them so the 422
    # doesn't itself blow up as a 500.
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(exc.errors())})


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": str(exc.detail)})


app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(gradebook.router)
app.include_router(lessons.router)
app.include_router(slides.router)
app.include_router(quiz_teacher.router)
app.include_router(quiz_student.router)
app.include_router(uploads.router)
app.include_router(students.router)
if settings.STORAGE_BACKEND == "local":
    if settings.SERVE_STATIC_VIA_NGINX:
        # nginx serves /files/* directly from disk; FastAPI only verifies sigs.
        app.include_router(files.internal_router)
    else:
        app.include_router(files.router)
app.include_router(analytics.router)
app.include_router(analytics.lesson_results_router)
app.include_router(comments.router)
app.include_router(billing.router)
app.include_router(assignment_teacher.router)
app.include_router(assignment_student.router)


@app.get("/", tags=["meta"])
async def root():
    return {"name": "Edllm API", "version": "0.1.0", "docs": "/docs"}


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
