from typing import Any
from uuid import UUID

import sentry_sdk
from fastapi import Cookie, Depends, Header, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.config import settings
from app.database import get_db
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.lesson import Lesson, Module
from app.models.user import User, UserRole
from app.redis_client import get_redis
from app.services.auth_service import decode_token

_STATE_CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


async def get_current_token_payload(
    request: Request,
    access_token: str | None = Cookie(default=None),
    csrf_token: str | None = Cookie(default=None),
    redis: Redis = Depends(get_redis),
) -> dict[str, Any]:
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    payload = decode_token(access_token)
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token type",
        )

    jti = payload.get("jti")
    if jti and await redis.get(f"blacklist:{jti}"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
        )

    # Double-submit CSRF check for state-changing requests.
    # The csrf_token cookie is non-httpOnly so JS can read and forward it;
    # an attacker's cross-site request cannot access it.
    if request.method in _STATE_CHANGING:
        csrf_header = request.headers.get("X-CSRF-Token")
        if not csrf_token or not csrf_header or csrf_header != csrf_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token invalid",
            )

    return payload


async def get_current_user(
    payload: dict[str, Any] = Depends(get_current_token_payload),
    db: AsyncSession = Depends(get_db),
) -> User:
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )

    # select (not db.get) so the global soft-delete filter excludes deleted users.
    user = await db.scalar(select(User).where(User.id == UUID(user_id)))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
    sentry_sdk.set_user({"id": str(user.id), "email": user.email})
    return user


async def check_csrf(
    request: Request,
    csrf_token: str | None = Cookie(default=None),
) -> None:
    """Standalone CSRF dependency — attach explicitly to endpoints that need
    CSRF protection without full auth (e.g. unauthenticated state changes)."""
    if request.method in _STATE_CHANGING:
        csrf_header = request.headers.get("X-CSRF-Token")
        if not csrf_token or not csrf_header or csrf_header != csrf_token:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="CSRF token invalid",
            )


async def require_teacher(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.teacher:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Teacher role required",
        )
    return user


async def require_verified_teacher(user: User = Depends(require_teacher)) -> User:
    """Teacher whose email is verified. Gate for content-creating/modifying
    endpoints only — GET and /auth/* stay open so an unverified teacher can sign
    in, browse, and trigger a resend, but cannot create content until verified."""
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please verify your email to create content.",
        )
    return user


async def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Gate for billing admin endpoints. There is no admin UserRole; access is
    granted by a shared secret (`ADMIN_API_TOKEN`) sent in the X-Admin-Token
    header. An empty configured token disables admin access entirely."""
    if not settings.ADMIN_API_TOKEN or x_admin_token != settings.ADMIN_API_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )


async def require_student(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student role required",
        )
    return user


async def require_lesson_access(
    lesson_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, Lesson, bool]:
    """Lesson-scoped access guard: teacher-owner OR enrolled student.

    Returns `(user, lesson, is_owner)`. Raises 404 if the lesson does not exist
    and 403 otherwise — matching the access semantics already used by
    `routers/students.py` (which 404s missing lessons and 403s non-enrolled).
    """
    lesson = await db.scalar(
        select(Lesson)
        .where(Lesson.id == lesson_id)
        .options(joinedload(Lesson.module).joinedload(Module.course))
    )
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")

    course = lesson.module.course
    if user.role == UserRole.teacher and course.owner_id == user.id:
        return user, lesson, True

    if user.role == UserRole.student:
        enrolled = await db.scalar(
            select(Enrollment.id).where(
                Enrollment.student_id == user.id,
                Enrollment.course_id == course.id,
            )
        )
        if enrolled is not None:
            return user, lesson, False

    raise HTTPException(status_code=403, detail="No access to this lesson")


async def get_owned_lesson(
    lesson_id: UUID,
    user: User = Depends(require_teacher),
    db: AsyncSession = Depends(get_db),
) -> Lesson:
    result = await db.execute(
        select(Lesson)
        .join(Module, Lesson.module_id == Module.id)
        .join(Course, Module.course_id == Course.id)
        .where(Lesson.id == lesson_id)
        .where(Course.owner_id == user.id)
        .options(joinedload(Lesson.module).joinedload(Module.course))
    )
    lesson = result.scalar_one_or_none()
    if lesson is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    return lesson
