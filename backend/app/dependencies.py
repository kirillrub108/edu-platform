from typing import Any
from uuid import UUID

from fastapi import Cookie, Depends, HTTPException, Request, status
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.database import get_db
from app.models.course import Course
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

    user = await db.get(User, UUID(user_id))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )
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


async def require_student(user: User = Depends(get_current_user)) -> User:
    if user.role != UserRole.student:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Student role required",
        )
    return user


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
