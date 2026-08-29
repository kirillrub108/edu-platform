"""Public profiles, avatars and the privacy rule that gates them.

Three things live here, deliberately together because they are one feature:

* **Access resolution.** `_visibility_allows` is the whole rule as a pure
  function; `resolve_profile_access` is the one async wrapper that answers the
  single question the rule cannot answer in memory ("is the viewer a teacher of
  a course this student is enrolled in?"). Routers never re-derive it.
  A denied profile answers **404**, not 403 — the API must not confirm that a
  hidden account exists, exactly as `require_lesson_access` hides drafts.

* **Profile contents.** Teacher and student profiles are assembled with a fixed
  number of statements each — no per-course query in a loop.

* **Avatars.** Two source columns collapse into one URL, uploads are re-encoded
  (which is also what strips EXIF), and provider URLs pass a host allowlist.

Privacy here is a *read* concern for this resource only. The gradebook,
course analytics and preview are a separate access contour and are untouched.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from io import BytesIO
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.constants import (
    AVATAR_PROVIDER_HOST_ALLOWLIST,
    AVATAR_SIZE_PX,
    AVATAR_STORAGE_EXT,
    AVATAR_URL_TTL_SECONDS,
    PROFILE_DEFAULT_STATS_STUDENT,
    PROFILE_DEFAULT_STATS_TEACHER,
    PROFILE_DEFAULT_VISIBILITY_STUDENT,
    PROFILE_DEFAULT_VISIBILITY_TEACHER,
    YANDEX_AVATAR_URL_TEMPLATE,
)
from app.models.assignment import AssignmentSubmission, SubmissionStatus
from app.models.course import Course
from app.models.enrollment import Enrollment
from app.models.lesson import Lesson, Module
from app.models.quiz import AttemptStatus, QuizAttempt
from app.models.user import ProfileVisibility, User, UserRole
from app.schemas.user import (
    ProfileCourseOut,
    ProfileOut,
    StudentStatsOut,
    TeacherStatsOut,
)
from app.services import visibility_service
from app.services.storage_service import storage_service

AVATAR_SUBFOLDER = "avatars"


@dataclass(frozen=True)
class ProfileAccess:
    """Outcome of the privacy rule for one (target, viewer) pair."""

    visible: bool
    stats_visible: bool
    is_owner: bool


# ── Privacy rule ─────────────────────────────────────────────────────────────


def _visibility_allows(
    visibility: ProfileVisibility,
    *,
    is_owner: bool,
    is_authenticated: bool,
    is_enrolling_teacher: bool,
) -> bool:
    """The rule, with no I/O so it can be reasoned about and tested directly."""
    if is_owner:
        return True
    if visibility == ProfileVisibility.public:
        return True
    if visibility == ProfileVisibility.authenticated:
        return is_authenticated
    # private: only the owner (handled above) and a teacher who actually teaches
    # this student — otherwise a teacher could not see their own roster.
    return is_enrolling_teacher


async def _teaches_student(db: AsyncSession, *, teacher_id: UUID, student_id: UUID) -> bool:
    found = await db.scalar(
        select(Enrollment.id)
        .join(Course, Enrollment.course_id == Course.id)
        .where(Enrollment.student_id == student_id, Course.owner_id == teacher_id)
        .limit(1)
    )
    return found is not None


async def resolve_profile_access(
    db: AsyncSession, target: User, viewer: User | None
) -> ProfileAccess:
    """Decide what `viewer` may see of `target`'s profile.

    A soft-deleted target is invisible to everyone, the owner included — the
    account is gone as far as this resource is concerned, and the owner's route
    back is restore, not their profile page.
    """
    if target.deleted_at is not None:
        return ProfileAccess(visible=False, stats_visible=False, is_owner=False)

    is_owner = viewer is not None and viewer.id == target.id
    is_enrolling_teacher = False
    if (
        not is_owner
        and target.profile_visibility == ProfileVisibility.private
        and viewer is not None
        and viewer.role == UserRole.teacher
        and target.role == UserRole.student
    ):
        is_enrolling_teacher = await _teaches_student(
            db, teacher_id=viewer.id, student_id=target.id
        )

    visible = _visibility_allows(
        target.profile_visibility,
        is_owner=is_owner,
        is_authenticated=viewer is not None,
        is_enrolling_teacher=is_enrolling_teacher,
    )
    # The owner always sees their own numbers; the toggle only governs others.
    stats_visible = visible and (is_owner or bool(target.show_profile_stats))
    return ProfileAccess(visible=visible, stats_visible=stats_visible, is_owner=is_owner)


def profile_defaults_for_role(role: UserRole) -> tuple[ProfileVisibility, bool]:
    """Role-dependent privacy defaults, applied at every account-creation path
    (password sign-up and OAuth completion) so the two cannot drift."""
    if role == UserRole.teacher:
        return (
            ProfileVisibility(PROFILE_DEFAULT_VISIBILITY_TEACHER),
            PROFILE_DEFAULT_STATS_TEACHER,
        )
    return (
        ProfileVisibility(PROFILE_DEFAULT_VISIBILITY_STUDENT),
        PROFILE_DEFAULT_STATS_STUDENT,
    )


# ── Avatars ──────────────────────────────────────────────────────────────────


def avatar_url(user: User) -> str | None:
    """The single avatar field the API exposes. An uploaded file wins over the
    provider's picture, so "use my Google avatar again" is a plain DELETE.

    The signed URL is minted under the *owner's* id because `uid` is only part
    of the HMAC payload, not an authorization check (routers/files.py) — so the
    link resolves for anonymous visitors too. That is intentional: an avatar is
    a public resource even on a private profile (DECISIONS §59).
    """
    if user.avatar_image_path:
        return storage_service.get_url(
            user.avatar_image_path, str(user.id), expires_in=AVATAR_URL_TTL_SECONDS
        )
    return user.avatar_external_url


def provider_avatar_url(provider: str, claims: dict[str, Any]) -> str | None:
    """Map an OAuth userinfo payload to an avatar URL, or None.

    Pure and total: unknown providers, missing claims and off-allowlist hosts
    all return None rather than raising, because a missing avatar must never
    fail a sign-in.
    """
    raw: str | None = None
    if provider == "google":
        picture = claims.get("picture")
        raw = picture if isinstance(picture, str) else None
    elif provider == "yandex":
        # Yandex hands out an id, not a URL, and flags "user has no avatar"
        # separately — without the flag check every account gets the default
        # grey silhouette instead of falling through to our own initials.
        if not claims.get("is_avatar_empty"):
            avatar_id = claims.get("default_avatar_id")
            if isinstance(avatar_id, (str, int)) and str(avatar_id).strip():
                raw = YANDEX_AVATAR_URL_TEMPLATE.format(avatar_id=str(avatar_id).strip())

    if not raw:
        return None
    parsed = urlparse(raw)
    if parsed.scheme != "https" or parsed.hostname not in AVATAR_PROVIDER_HOST_ALLOWLIST:
        return None
    return raw


def apply_provider_avatar(user: User, provider: str, claims: dict[str, Any]) -> None:
    """Refresh the provider-side avatar on every social sign-in — the picture on
    the other side may have changed since last time. Clearing it when the
    provider stops offering one is equally intentional."""
    user.avatar_external_url = provider_avatar_url(provider, claims)


def normalize_avatar(data: bytes) -> bytes:
    """Re-encode an uploaded image to one square WEBP of AVATAR_SIZE_PX.

    Re-encoding is what removes EXIF: `save()` writes no EXIF block unless
    handed one, so the GPS tag phones embed never reaches storage. Orientation
    is applied first so stripping the tag does not rotate the picture.
    """
    from PIL import Image, ImageOps

    with Image.open(BytesIO(data)) as img:
        oriented = ImageOps.exif_transpose(img) or img
        square = ImageOps.fit(
            oriented.convert("RGB"), (AVATAR_SIZE_PX, AVATAR_SIZE_PX), centering=(0.5, 0.5)
        )
        out = BytesIO()
        square.save(out, format="WEBP", quality=85)
    return out.getvalue()


def avatar_prefix(user_id: UUID | str) -> str:
    return f"{AVATAR_SUBFOLDER}/{user_id}"


async def store_avatar(user: User, data: bytes) -> str:
    """Normalize and store, replacing whatever was there.

    The whole per-user prefix is dropped first, so a replaced avatar cannot
    leave an orphan behind — there is no old-path bookkeeping to get wrong.
    """
    normalized = normalize_avatar(data)
    storage_service.delete_prefix(avatar_prefix(user.id))
    relative = f"{avatar_prefix(user.id)}/{uuid.uuid4().hex}{AVATAR_STORAGE_EXT}"
    await storage_service.save_bytes(relative, normalized)
    user.avatar_image_path = relative
    return relative


def drop_avatar_file(user_id: UUID | str) -> None:
    """Remove stored avatar bytes. Separate from field mutation so the sync
    purge task can call it next to the pure anonymize function."""
    storage_service.delete_prefix(avatar_prefix(user_id))


# ── Profile assembly ─────────────────────────────────────────────────────────


async def _teacher_profile(
    db: AsyncSession, target: User, access: ProfileAccess
) -> tuple[list[ProfileCourseOut], TeacherStatsOut | None]:
    # Published and not archived: a profile is discovery, and discovery is
    # exactly what course publication gates (DECISIONS §34/§51).
    courses = (
        await db.scalars(
            select(Course)
            .where(
                Course.owner_id == target.id,
                Course.is_published.is_(True),
                Course.deleted_at.is_(None),
            )
            .options(selectinload(Course.modules).selectinload(Module.lessons))
            .order_by(Course.created_at.desc())
        )
    ).all()

    rows = [
        ProfileCourseOut(
            id=course.id,
            title=course.title,
            description=course.description,
            cover_image_url=_course_cover_url(course, str(target.id)),
            lessons_count=sum(
                1
                for module in course.modules
                for lesson in module.lessons
                if visibility_service.lesson_visible_to_student(module, lesson)
            ),
        )
        for course in courses
    ]

    if not access.stats_visible:
        return rows, None

    # One statement, count(distinct) rather than a join fan-out per metric.
    stats_row = (
        await db.execute(
            select(
                func.count(func.distinct(Course.id)),
                func.count(func.distinct(Lesson.id)),
                func.count(func.distinct(Enrollment.id)),
            )
            .select_from(Course)
            .outerjoin(Module, Module.course_id == Course.id)
            .outerjoin(Lesson, Lesson.module_id == Module.id)
            .outerjoin(Enrollment, Enrollment.course_id == Course.id)
            .where(
                Course.owner_id == target.id,
                Course.is_published.is_(True),
                Course.deleted_at.is_(None),
            )
        )
    ).one()
    return rows, TeacherStatsOut(
        courses_count=int(stats_row[0] or 0),
        lessons_count=int(stats_row[1] or 0),
        students_count=int(stats_row[2] or 0),
    )


async def _student_profile(
    db: AsyncSession, target: User, access: ProfileAccess
) -> tuple[list[ProfileCourseOut], StudentStatsOut | None]:
    enrollments = (
        await db.scalars(
            select(Enrollment)
            .where(Enrollment.student_id == target.id)
            .options(
                selectinload(Enrollment.course)
                .selectinload(Course.modules)
                .selectinload(Module.lessons),
                selectinload(Enrollment.progress),
            )
            .order_by(Enrollment.enrolled_at.desc())
        )
    ).all()

    rows: list[ProfileCourseOut] = []
    completed_total = 0
    for enrollment in enrollments:
        course = enrollment.course
        if course is None or course.deleted_at is not None:
            continue
        visible_lesson_ids = {
            lesson.id
            for module in course.modules
            for lesson in module.lessons
            if visibility_service.lesson_visible_to_student(module, lesson)
        }
        # Count progress only for lessons still visible, so the percentage can
        # never exceed 100 after a teacher unpublishes something.
        done = sum(
            1 for p in enrollment.progress if p.is_completed and p.lesson_id in visible_lesson_ids
        )
        completed_total += done
        total = len(visible_lesson_ids)
        rows.append(
            ProfileCourseOut(
                id=course.id,
                title=course.title,
                description=course.description,
                cover_image_url=_course_cover_url(course, str(target.id)),
                lessons_count=total,
                progress_percent=round(done / total * 100, 1) if total else 0.0,
            )
        )

    if not access.stats_visible:
        return rows, None

    avg_quiz = await db.scalar(
        select(func.avg(QuizAttempt.score)).where(
            QuizAttempt.student_id == target.id,
            QuizAttempt.status.in_([AttemptStatus.submitted, AttemptStatus.graded]),
            QuizAttempt.score.isnot(None),
        )
    )
    avg_assignment = await db.scalar(
        select(func.avg(AssignmentSubmission.score))
        .join(Enrollment, AssignmentSubmission.enrollment_id == Enrollment.id)
        .where(
            Enrollment.student_id == target.id,
            AssignmentSubmission.status.in_([SubmissionStatus.graded, SubmissionStatus.returned]),
            AssignmentSubmission.score.isnot(None),
        )
    )
    return rows, StudentStatsOut(
        completed_lessons=completed_total,
        # Both columns store 0..1; the API speaks percent everywhere else.
        avg_quiz_score=round(float(avg_quiz) * 100, 1) if avg_quiz is not None else None,
        avg_assignment_score=(
            round(float(avg_assignment) * 100, 1) if avg_assignment is not None else None
        ),
    )


def _course_cover_url(course: Course, user_id: str) -> str | None:
    if course.cover_image_path:
        return storage_service.get_url(course.cover_image_path, user_id)
    return storage_service.resign_url(course.cover_url, user_id)


async def get_profile(db: AsyncSession, target: User, access: ProfileAccess) -> ProfileOut:
    """Assemble the profile payload. Caller has already checked `access.visible`."""
    if target.role == UserRole.teacher:
        courses, teacher_stats = await _teacher_profile(db, target, access)
        student_stats = None
    else:
        courses, student_stats = await _student_profile(db, target, access)
        teacher_stats = None

    return ProfileOut(
        id=target.id,
        full_name=target.full_name,
        bio=target.bio,
        role=target.role,
        created_at=target.created_at,
        avatar_url=avatar_url(target),
        courses=courses,
        teacher_stats=teacher_stats,
        student_stats=student_stats,
        is_owner=access.is_owner,
        profile_visibility=target.profile_visibility if access.is_owner else None,
        show_profile_stats=target.show_profile_stats if access.is_owner else None,
    )
