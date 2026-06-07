import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, String
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class UserRole(str, enum.Enum):
    teacher = "teacher"
    student = "student"


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
    hashed_password = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    role = Column(
        SAEnum(UserRole, name="user_role"),
        default=UserRole.teacher,
        nullable=False,
    )
    is_active = Column(Boolean, default=True, nullable=False)
    # Soft delete: non-null = hidden everywhere (see app/database.py global filter)
    # and slated for physical purge after SOFT_DELETE_PURGE_DAYS.
    deleted_at = Column(DateTime(timezone=True), nullable=True, default=None, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    courses = relationship("Course", back_populates="owner", cascade="all, delete-orphan")
    enrollments = relationship("Enrollment", back_populates="student", cascade="all, delete-orphan")
