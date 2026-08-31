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
from app.models.lesson import ContentType, Lesson, Module
from app.models.user import User, UserRole
from app.redis_client import get_redis
from app.services import course_access_service, visibility_service
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


async def get_optional_user(
    access_token: str | None = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Current user when there is one, None when anonymous — for routes that
    are readable without logging in but answer differently when you are.

    Deliberately NOT built on get_current_token_payload: that dependency raises
    on a missing or stale cookie, and here every one of those cases is simply
    "anonymous". It also skips the CSRF branch, which is safe because this is
    only used on GET routes.
    """
    if not access_token:
        return None
    try:
        payload = decode_token(access_token)
    except HTTPException:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    try:
        parsed = UUID(user_id)
    except ValueError:
        return None
    user = await db.scalar(select(User).where(User.id == parsed))
    return user if user and user.is_active else None


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


async def require_verified_email(user: User = Depends(get_current_user)) -> User:
    """AI-operation gate: any authenticated user whose email is verified. Role
    and ownership checks are layered separately by the route's other
    dependencies (e.g. `get_owned_lesson`). The machine-readable
    `email_not_verified` detail is the contract the frontend's bypass-guard
    relies on. See AI_GATED_ENDPOINTS below."""
    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="email_not_verified",
        )
    return user


# Every endpoint that triggers an LLM / vision / TTS operation must sit behind
# `require_verified_email` or `require_verified_teacher`. This registry is the
# source of truth the guard test (tests/integration/test_ai_gating_guard.py)
# checks against: adding a new AI route means adding it here AND gating it, or
# the guard test fails. Student quiz grading is intentionally excluded — see
# docs/DECISIONS.md.
AI_GATED_ENDPOINTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/lessons/{lesson_id}/analyze"),
        ("POST", "/api/v1/lessons/{lesson_id}/generate-video"),
        ("POST", "/api/v1/lessons/{lesson_id}/slides/{slide_id}/regenerate"),
        ("POST", "/api/v1/lessons/{lesson_id}/quiz/generate"),
        ("POST", "/api/v1/lessons/{lesson_id}/quiz/questions/{question_id}/regenerate"),
        ("POST", "/api/v1/lessons/{lesson_id}/quiz/ai-review"),
        ("GET", "/api/v1/tts/sample"),
    }
)


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

    "Enrolled" means `course_access_service.has_access` — on a restricted course
    an Enrollment alone is not enough, the owner must also have granted access.

    Returns `(user, lesson, is_owner)`. Raises 404 if the lesson does not exist
    and 403 otherwise — matching the access semantics already used by
    `routers/students.py` (which 404s missing lessons and 403s non-enrolled).
    """
    # The retained-progress EXISTS rides along in this query rather than costing
    # a second round-trip on an already chatty hot path.
    row = (
        await db.execute(
            select(Lesson, visibility_service.lesson_progress_exists(Lesson.id, user.id))
            .where(Lesson.id == lesson_id)
            .options(joinedload(Lesson.module).joinedload(Module.course))
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Lesson not found")
    lesson, has_progress = row

    course = lesson.module.course
    if user.role == UserRole.teacher and course.owner_id == user.id:
        return user, lesson, True

    if user.role == UserRole.student:
        if await course_access_service.has_access(db, user.id, course.id):
            # Unpublished module/lesson is hidden — 404 (not 403) so we don't
            # reveal that a draft exists, unless this student already has
            # progress on it. course.is_published is intentionally not checked:
            # an enrolled student keeps access after the course is unpublished
            # (single source of truth: visibility_service).
            if not visibility_service.lesson_visible_to_student(
                lesson.module, lesson, bool(has_progress)
            ):
                raise HTTPException(status_code=404, detail="Lesson not found")
            return user, lesson, False

    raise HTTPException(status_code=403, detail="No access to this lesson")


def assert_not_text_lesson(lesson: Lesson) -> None:
    """Text lessons have no slides, script or video — every generation entry
    point refuses them explicitly instead of failing deep in the pipeline."""
    if lesson.content_type == ContentType.text:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "text_lesson_no_video",
                "message": (
                    "Это текстовый урок: презентация, озвучка и генерация видео "
                    "для него недоступны."
                ),
            },
        )


async def require_course_access(
    course_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> tuple[User, Course, bool]:
    """Course-scoped access guard: teacher-owner OR enrolled student.

    Returns `(user, course, is_owner)`. Mirrors `require_lesson_access` one level
    up, and matches routers/students.py:course_details — a missing course is 404,
    a non-enrolled viewer 403. `deleted_at` is deliberately not filtered for an
    enrolled student: archiving a course is teacher-facing and never revokes the
    access of someone already enrolled (docs/DECISIONS.md §51).
    """
    course = await db.scalar(select(Course).where(Course.id == course_id))
    if course is None:
        raise HTTPException(status_code=404, detail="Course not found")

    if user.role == UserRole.teacher and course.owner_id == user.id:
        return user, course, True

    if user.role == UserRole.student:
        if await course_access_service.has_access(db, user.id, course.id):
            return user, course, False

    raise HTTPException(status_code=403, detail="No access to this course")


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
