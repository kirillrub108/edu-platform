import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import engine
from app.limiter import limiter
from app.redis_client import close_redis
from app.routers import auth, courses, files, lessons, slides, students, uploads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def _ensure_schema_at_head() -> None:
    """Run any pending Alembic migrations on startup so the schema always
    matches the latest revision in code. Replaces the old metadata.create_all
    bootstrap, which silently diverged from migration history and caused
    'type already exists' errors on first `alembic upgrade head`.
    """
    from alembic import command
    from alembic.config import Config

    cfg = Config("/app/alembic.ini")
    cfg.set_main_option("script_location", "/app/alembic")
    cfg.set_main_option("sqlalchemy.url", settings.DATABASE_URL.replace("+asyncpg", "+psycopg2"))

    def _upgrade() -> None:
        command.upgrade(cfg, "head")

    await asyncio.to_thread(_upgrade)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection OK")
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)

    try:
        await _ensure_schema_at_head()
        logger.info("Alembic migrations applied (head)")
    except Exception:
        logger.exception("Alembic upgrade failed; refusing to start with stale schema")
        raise

    yield
    await engine.dispose()
    await close_redis()


app = FastAPI(
    title="Edu Platform API",
    description="AI-platform for creating and delivering educational content",
    version="0.1.0",
    lifespan=lifespan,
)
app.state.limiter = limiter

# ── Middleware order ──────────────────────────────────────────────────────────
# In modern Starlette, `app.add_middleware()` *prepends* to user_middleware
# (insert(0, ...)), so the LAST middleware registered ends up OUTERMOST. We
# need this stack from outside in:
#
#     ServerErrorMiddleware   (built-in, always outermost)
#       → CORSMiddleware       ← MUST be outside log_and_catch so the 500
#         → log_and_catch      ← JSONResponse it returns flows back through
#           → ExceptionMiddleware
#             → routes
#
# That way CORS headers are attached to *every* response, including the
# fall-back 500 from `log_and_catch`. If CORS sits *inside* log_and_catch, a
# backend bug surfaces in the browser as a misleading "CORS policy" error
# (because the 500 response ships without Access-Control-Allow-Origin).
#
# Therefore: register `log_and_catch` FIRST, then CORS LAST.

@app.middleware("http")
async def log_and_catch(request: Request, call_next):
    """Access log + last-resort 500 handler. Sits inside CORS in the stack."""
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = (time.perf_counter() - start) * 1000
        logger.exception(
            "Unhandled error in %s %s (%.1fms): %s",
            request.method,
            request.url.path,
            elapsed_ms,
            exc,
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "%s %s -> %d (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


_cors_origins = settings.CORS_ORIGINS
_allow_all = "*" in _cors_origins

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
    return JSONResponse(status_code=422, content={"detail": exc.errors()})


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": str(exc.detail)})


app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(lessons.router)
app.include_router(slides.router)
app.include_router(uploads.router)
app.include_router(students.router)
app.include_router(files.router)


@app.get("/", tags=["meta"])
async def root():
    return {"name": "Edu Platform API", "version": "0.1.0", "docs": "/docs"}


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
