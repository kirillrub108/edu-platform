from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from app.constants import (
    AVATAR_URL_TTL_SECONDS,
    PROFILE_MAX_BIO_CHARS,
    PROFILE_MAX_FULL_NAME_CHARS,
)
from app.models.user import ProfileVisibility, UserRole
from app.services.storage_service import storage_service


class UserBase(BaseModel):
    email: EmailStr
    full_name: str | None = None


class UserOut(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: UserRole
    is_active: bool
    email_verified: bool
    created_at: datetime
    # Source columns for avatar_url below; excluded from the response so the
    # client sees one field, same shape as CommentAuthor.
    avatar_image_path: str | None = Field(default=None, exclude=True)
    avatar_external_url: str | None = Field(default=None, exclude=True)

    @computed_field
    @property
    def avatar_url(self) -> str | None:
        # Mirrors profile_service.avatar_url: uploaded wins over the provider's,
        # signed under the owner's own id (`uid` is HMAC payload, not an ACL).
        if self.avatar_image_path:
            return storage_service.get_url(
                self.avatar_image_path, str(self.id), expires_in=AVATAR_URL_TTL_SECONDS
            )
        return self.avatar_external_url


# ── Own settings (/users/me/*) ───────────────────────────────────────────────


class ProfileUpdate(BaseModel):
    """PATCH /users/me/profile. Both fields optional — an absent key means
    "leave it alone", an explicit null clears it."""

    full_name: str | None = Field(default=None, max_length=PROFILE_MAX_FULL_NAME_CHARS)
    bio: str | None = Field(default=None, max_length=PROFILE_MAX_BIO_CHARS)

    @field_validator("full_name", "bio")
    @classmethod
    def _blank_to_null(cls, v: str | None) -> str | None:
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None


class ProfileSettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    full_name: str | None
    bio: str | None
    avatar_url: str | None = None


class PrivacyUpdate(BaseModel):
    profile_visibility: ProfileVisibility | None = None
    show_profile_stats: bool | None = None


class PrivacySettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    profile_visibility: ProfileVisibility
    show_profile_stats: bool


# ── Public profile (/users/{id}/profile) ─────────────────────────────────────


class ProfileCourseOut(BaseModel):
    """One course row on a profile. Deliberately thinner than CourseOut: no
    access code, no publish flags, no owner — a profile is a shop window."""

    id: UUID
    title: str
    description: str | None = None
    cover_image_url: str | None = None
    lessons_count: int = 0
    # Student profiles only: how far this student got, 0..100.
    progress_percent: float | None = None


class TeacherStatsOut(BaseModel):
    courses_count: int
    lessons_count: int
    students_count: int


class StudentStatsOut(BaseModel):
    completed_lessons: int
    # 0..100, null when the student has no graded work of that kind yet.
    avg_quiz_score: float | None = None
    avg_assignment_score: float | None = None


class ProfileOut(BaseModel):
    """Public profile payload. Carries no email and nothing billing-related at
    any visibility — those are not "hidden by privacy", they are simply not
    part of this resource."""

    id: UUID
    full_name: str | None
    bio: str | None
    role: UserRole
    created_at: datetime
    avatar_url: str | None = None
    courses: list[ProfileCourseOut] = Field(default_factory=list)
    # Null when the owner turned stats off — identity, avatar and courses stay.
    teacher_stats: TeacherStatsOut | None = None
    student_stats: StudentStatsOut | None = None
    # True only for the owner reading their own profile. Lets the SPA show the
    # "this is what others see" banner without a second request.
    is_owner: bool = False
    # Owner-only echo of the current settings, so the banner can be specific.
    profile_visibility: ProfileVisibility | None = None
    show_profile_stats: bool | None = None
