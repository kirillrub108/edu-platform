import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.routers import auth, courses, lessons, slides, students, uploads

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


app = FastAPI(
    title="Edu Platform API",
    description="AI-platform for creating and delivering educational content",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS — allow all origins in development so browser never sees CORS errors
# on internal crashes. Switch to specific origins in production.
_cors_origins = settings.CORS_ORIGINS
_allow_all = "*" in _cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_all else _cors_origins,
    allow_credentials=False if _allow_all else True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
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


app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(lessons.router)
app.include_router(slides.router)
app.include_router(uploads.router)
app.include_router(students.router)

app.mount(
    "/files",
    StaticFiles(directory=settings.STORAGE_PATH, check_dir=False),
    name="files",
)


@app.get("/", tags=["meta"])
async def root():
    return {"name": "Edu Platform API", "version": "0.1.0", "docs": "/docs"}


@app.get("/health", tags=["meta"])
async def health():
    return {"status": "ok"}
