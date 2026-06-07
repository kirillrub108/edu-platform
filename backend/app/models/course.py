import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class AccessMode(str, enum.Enum):
    link = "link"
    code = "code"
    invite = "invite"


class Course(Base):
    __tablename__ = "courses"
    # See User.__mapper_args__ for rationale — UPDATE on `is_published` etc.
    # without `eager_defaults` leaves `updated_at` expired and breaks Pydantic
    # serialization with `MissingGreenlet`.
    __mapper_args__ = {"eager_defaults": True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    cover_url = Column(String(512), nullable=True)
    owner_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )  # noqa: E501
    access_mode = Column(
        SAEnum(AccessMode, name="access_mode"),
        default=AccessMode.link,
        nullable=False,
    )
    access_code = Column(String(20), nullable=True, unique=True)
    is_published = Column(Boolean, default=False, nullable=False)
    # Soft delete (archive). Unlike User/Lesson this is NOT filtered globally —
    # teachers must still see archived courses (see app/database.py comment).
    deleted_at = Column(DateTime(timezone=True), nullable=True, default=None, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    owner = relationship("User", back_populates="courses")
    modules = relationship(
        "Module",
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="Module.order",
    )
    enrollments = relationship("Enrollment", back_populates="course")
