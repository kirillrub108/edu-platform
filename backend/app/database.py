from typing import AsyncGenerator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session, declarative_base, with_loader_criteria

from app.config import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)

Base = declarative_base()


# ── Global soft-delete filter ───────────────────────────────────────────────
# Transparently appends `deleted_at IS NULL` to every ORM SELECT for User and
# Lesson, so soft-deleted rows are invisible app-wide ("full hide"). Registered
# on the sync Session class that backs AsyncSession, so it covers all app
# (async) queries.
#
# Course is deliberately EXCLUDED: teachers must still see archived courses in
# the dashboard "Архив" section. Course archive visibility is handled instead by
# explicit `Course.deleted_at.is_(None)` filters in the student-facing routers
# (routers/students.py) — the teacher routers intentionally see archived rows.
#
# Caveats this compensates for elsewhere:
#   * `Session.get()` is NOT intercepted by with_loader_criteria — callers that
#     must respect the filter use `select(...).where(...)` instead of `db.get`.
#   * The Celery purge worker needs to SEE soft-deleted rows; it opts out per
#     query with `.execution_options(include_deleted=True)`.
@event.listens_for(Session, "do_orm_execute")
def _filter_soft_deleted(execute_state: "object") -> None:
    state = execute_state  # type: ignore[assignment]
    if (
        state.is_select
        and not state.is_column_load
        and not state.is_relationship_load
        and not state.execution_options.get("include_deleted", False)
    ):
        # Imported lazily: models import Base from this module at import time.
        from app.models.lesson import Lesson
        from app.models.user import User

        state.statement = state.statement.options(
            with_loader_criteria(
                User, lambda cls: cls.deleted_at.is_(None), include_aliases=True
            ),
            with_loader_criteria(
                Lesson, lambda cls: cls.deleted_at.is_(None), include_aliases=True
            ),
        )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
