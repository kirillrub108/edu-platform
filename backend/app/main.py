import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.routers import auth, courses, lessons, students, uploads

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection OK")
    except Exception as exc:
        logger.error("Database connection failed: %s", exc)
    yield
    await engine.dispose()


app = FastAPI(
    title="Edu Platform API",
    description="AI-platform for creating and delivering educational content",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
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
