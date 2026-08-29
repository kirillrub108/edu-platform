import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.constants import (
    PROFILE_DEFAULT_STATS_STUDENT,
    PROFILE_DEFAULT_VISIBILITY_STUDENT,
)
from app.database import Base


class UserRole(str, enum.Enum):
    teacher = "teacher"
    student = "student"


class ProfileVisibility(str, enum.Enum):
    """Who may read GET /users/{id}/profile. Enforced in profile_service, never
    inline — and an unreadable profile answers 404, not 403, so the API never
    confirms that a hidden account exists (same rule as unpublished lessons)."""

    public = "public"
    authenticated = "authenticated"
    private = "private"


class User(Base):
    __tablename__ = "users"
    # `eager_defaults=True` makes SQLAlchemy add a RETURNING clause to INSERT
    # AND UPDATE statements so that columns with server-side defaults
    # (`server_default=func.now()`, `onupdate=func.now()`) are populated
    # in-place after `await db.commit()`. Without this, `updated_at` is left
    # in the "expired" state after UPDATE; later attribute access (e.g. by
    # Pydantic during response serialization) triggers a sync lazy-load,
    # which crashes async sessions with `MissingGreenlet`.
    __mapper_args__ = {"eager_defaults": True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, index=True, nullable=False)
    # Nullable: an account created purely through an OAuth provider has no
    # local password. Such users log in via the provider; reset-password can
    # later set one (see services/oauth_service.py).
    hashed_password = Column(String(255), nullable=True)
    full_name = Column(String(255), nullable=True)
    bio = Column(Text, nullable=True)
    # Avatar, mirroring the course-cover pair: an uploaded file (relative
    # storage path) and a provider-supplied URL. The serializer collapses both
    # into a single `avatar_url` and prefers the uploaded one, so "go back to my
    # Google picture" is just DELETE of the upload — no third switch column.
    avatar_image_path = Column(String(512), nullable=True)
    avatar_external_url = Column(String(512), nullable=True)
    profile_visibility = Column(
        SAEnum(ProfileVisibility, name="profile_visibility"),
        server_default=PROFILE_DEFAULT_VISIBILITY_STUDENT,
        default=ProfileVisibility(PROFILE_DEFAULT_VISIBILITY_STUDENT),
        nullable=False,
    )
    show_profile_stats = Column(
        Boolean,
        server_default="true" if PROFILE_DEFAULT_STATS_STUDENT else "false",
        default=PROFILE_DEFAULT_STATS_STUDENT,
        nullable=False,
    )
    role = Column(
        SAEnum(UserRole, name="user_role"),
        default=UserRole.teacher,
        nullable=False,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    # Email ownership proof. New registrations start False and must click the
    # signed verification link; content-creating teacher endpoints are gated on
    # this via require_verified_teacher. Existing users are backfilled to True.
    email_verified = Column(Boolean, server_default="false", nullable=False, default=False)
    # Product-notification preferences (see services/notification_service.py).
    # One column per NotificationCategory — the enum's value IS the column name.
    # Default on: a user who never visits the settings page still gets told when
    # their lecture is ready. Auth mail ignores these flags entirely.
    notify_content = Column(Boolean, server_default="true", nullable=False, default=True)
    notify_feedback = Column(Boolean, server_default="true", nullable=False, default=True)
    notify_submissions = Column(Boolean, server_default="true", nullable=False, default=True)
    # Soft delete: non-null = hidden everywhere (see app/database.py global filter)
    # and slated for physical purge after SOFT_DELETE_PURGE_DAYS.
    deleted_at = Column(DateTime(timezone=True), nullable=True, default=None, index=True)
    # Registration consents. All set on the server at sign-up (see AuthService.
    # register); IP comes from the request, never the body. Nullable because
    # pre-existing users have no recorded consent.
    pdn_consent_at = Column(DateTime(timezone=True), nullable=True)
    terms_accepted_at = Column(DateTime(timezone=True), nullable=True)
    marketing_consent = Column(Boolean, server_default="false", nullable=False, default=False)
    marketing_consent_at = Column(DateTime(timezone=True), nullable=True)
    consent_policy_version = Column(String(32), nullable=True)
    consent_ip = Column(String(45), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    courses = relationship("Course", back_populates="owner", cascade="all, delete-orphan")
    enrollments = relationship("Enrollment", back_populates="student", cascade="all, delete-orphan")
