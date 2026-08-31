"""Single source of truth for *whether a student may reach a course at all*.

This sits one layer above `visibility_service`, it does not replace it:

* `course_access_service` — "is this student allowed onto the course?"
  (`Enrollment` exists AND the course is open OR the student was explicitly
  granted access).
* `visibility_service` — "of that course, which modules/lessons are published?"

Every student-facing path that used to gate on a bare `Enrollment` lookup goes
through `get_enrollment` / `has_access` here; list queries that need the rule as
SQL use `access_clause`.
"""

import json
from typing import Any, Literal
from uuid import UUID

import structlog
from redis.asyncio import Redis
from sqlalchemy import ColumnElement, delete, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.course import AccessMode, Course, CourseAccessGrant
from app.models.enrollment import Enrollment

logger = structlog.get_logger()

AccessChange = Literal["granted", "revoked"]


def is_restricted(course: Course) -> bool:
    """`invite` is the restricted mode; `link`/`code` are both open."""
    return course.access_mode == AccessMode.invite


def access_clause(student_id: UUID | ColumnElement[Any]) -> ColumnElement[bool]:
    """The "course is open OR explicitly granted" half of the rule, as a WHERE
    fragment for queries that already have `Course` in the FROM. Pair it with
    the `Enrollment.student_id` filter those queries already carry.

    `student_id` may also be a column (e.g. `Enrollment.student_id`) to evaluate
    the rule per row instead of for one fixed student — that is what the comment
    notification fan-out does.
    """
    return or_(
        Course.access_mode != AccessMode.invite,
        select(CourseAccessGrant.id)
        .where(
            CourseAccessGrant.course_id == Course.id,
            CourseAccessGrant.student_id == student_id,
        )
        .exists(),
    )


async def get_enrollment(db: AsyncSession, student_id: UUID, course_id: UUID) -> Enrollment | None:
    """The full rule in one query. `None` means "no access" — callers answer
    403 (or 404 where existence must not leak), exactly as before.
    """
    return await db.scalar(
        select(Enrollment)
        .join(Course, Enrollment.course_id == Course.id)
        .where(
            Enrollment.student_id == student_id,
            Enrollment.course_id == course_id,
            access_clause(student_id),
        )
    )


async def has_access(db: AsyncSession, student_id: UUID, course_id: UUID) -> bool:
    return await get_enrollment(db, student_id, course_id) is not None


async def has_grant(db: AsyncSession, student_id: UUID, course_id: UUID) -> bool:
    granted = await db.scalar(
        select(CourseAccessGrant.id).where(
            CourseAccessGrant.course_id == course_id,
            CourseAccessGrant.student_id == student_id,
        )
    )
    return granted is not None


async def grant_access(
    db: AsyncSession, course_id: UUID, student_id: UUID, granted_by_id: UUID
) -> None:
    """Idempotent: a concurrent duplicate is absorbed by the UNIQUE index
    instead of surfacing as an IntegrityError. Also ensures the Enrollment the
    access rule is built on, so adding a student is a single teacher action."""
    await db.execute(
        pg_insert(CourseAccessGrant)
        .values(course_id=course_id, student_id=student_id, granted_by_id=granted_by_id)
        .on_conflict_do_nothing(constraint="uq_course_access_grant_course_student")
    )
    await db.execute(
        pg_insert(Enrollment)
        .values(course_id=course_id, student_id=student_id)
        .on_conflict_do_nothing(constraint="uq_enrollment_student_course")
    )
    await db.commit()


async def backfill_grants_from_enrollments(
    db: AsyncSession, course_id: UUID, granted_by_id: UUID
) -> None:
    """Switching a course to restricted must not evict anyone already on it, so
    every existing Enrollment gets a grant. One INSERT…SELECT, re-runnable."""
    await db.execute(
        pg_insert(CourseAccessGrant)
        .from_select(
            ["id", "course_id", "student_id", "granted_by_id"],
            select(
                func.gen_random_uuid(),
                Enrollment.course_id,
                Enrollment.student_id,
                literal(granted_by_id),
            ).where(Enrollment.course_id == course_id),
        )
        .on_conflict_do_nothing(constraint="uq_course_access_grant_course_student")
    )


async def revoke_access(db: AsyncSession, course_id: UUID, student_id: UUID) -> None:
    """Drops the grant only. The Enrollment and everything hanging off it —
    progress, grades, submissions — stays, so the gradebook keeps its history.
    Idempotent: revoking a grant that isn't there is a no-op."""
    await db.execute(
        delete(CourseAccessGrant).where(
            CourseAccessGrant.course_id == course_id,
            CourseAccessGrant.student_id == student_id,
        )
    )
    await db.commit()


def courses_channel(student_id: UUID | str) -> str:
    """Per-student pub/sub channel behind the cabinet's course-access stream."""
    return f"student:{student_id}:courses"


async def publish_access_change(
    redis: Redis, student_id: UUID, course_id: UUID, event: AccessChange
) -> None:
    """Best effort by design: a Redis outage must not fail the teacher's action.
    The student's cabinet also refetches when the tab regains focus, so a lost
    message costs latency, not correctness."""
    try:
        await redis.publish(
            courses_channel(student_id),
            json.dumps({"event": event, "course_id": str(course_id)}),
        )
    except Exception:
        logger.warning("course_access_publish_failed", student_id=str(student_id), change=event)
