import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class Enrollment(Base):
    __tablename__ = "enrollments"
    __table_args__ = (
        UniqueConstraint("student_id", "course_id", name="uq_enrollment_student_course"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    student_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # RESTRICT (not CASCADE) so soft-deleted courses keep their enrollment history.
    # Hard-deleting a course with enrollments raises IntegrityError → 409 in the router.
    course_id = Column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False
    )
    enrolled_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    student = relationship("User", back_populates="enrollments")
    course = relationship("Course", back_populates="enrollments")
    progress = relationship(
        "LessonProgress", back_populates="enrollment", cascade="all, delete-orphan"
    )


class LessonProgress(Base):
    __tablename__ = "lesson_progress"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint("enrollment_id", "lesson_id", name="uq_lesson_progress_enrollment_lesson"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enrollment_id = Column(
        UUID(as_uuid=True), ForeignKey("enrollments.id", ondelete="CASCADE"), nullable=False
    )
    lesson_id = Column(
        UUID(as_uuid=True), ForeignKey("lessons.id", ondelete="CASCADE"), nullable=False
    )
    is_completed = Column(Boolean, default=False, nullable=False)
    quiz_score = Column(Float, nullable=True)
    manual_override_score = Column(Float, nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    manual_score = Column(Float, nullable=True)
    teacher_comment = Column(Text, nullable=True)
    edited_by_teacher = Column(Boolean, nullable=False, server_default="false", default=False)
    edit_reason = Column(String(500), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    enrollment = relationship("Enrollment", back_populates="progress")
