import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class AccessMode(str, enum.Enum):
    """How students get onto a course.

    `link`/`code` are both *open*: anyone holding the link or the access code
    can self-enroll. `invite` is the *restricted* mode — self-enrollment is
    refused and only students the owner listed in `CourseAccessGrant` may reach
    the course (see services/course_access_service.py).
    """

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
    cover_image_path = Column(String(512), nullable=True)
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
    access_grants = relationship(
        "CourseAccessGrant", back_populates="course", cascade="all, delete-orphan"
    )


class CourseAccessGrant(Base):
    """An explicit "this student may use this course" entry, meaningful only
    while the course is in `AccessMode.invite`. Revoking a grant leaves the
    Enrollment (and therefore the progress/grades hanging off it) intact — the
    teacher keeps seeing the student in the gradebook.
    """

    __tablename__ = "course_access_grants"
    __table_args__ = (
        UniqueConstraint("course_id", "student_id", name="uq_course_access_grant_course_student"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    student_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    granted_by_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    course = relationship("Course", back_populates="access_grants")
    student = relationship("User", foreign_keys=[student_id])
