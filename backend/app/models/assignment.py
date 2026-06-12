import enum
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class AssignmentStatus(str, enum.Enum):
    draft = "draft"
    published = "published"


class SubmissionStatus(str, enum.Enum):
    draft = "draft"          # student is still editing (re-submittable)
    submitted = "submitted"  # handed in, awaiting grading
    graded = "graded"        # graded but not yet released to the student
    returned = "returned"    # graded AND released — student sees score/feedback


class AttachmentKind(str, enum.Enum):
    submission = "submission"  # uploaded by the student with their answer
    feedback = "feedback"      # uploaded by the teacher alongside the grade


class Assignment(Base):
    """A text task a teacher attaches to a lesson (1:N). Publish/unpublish is an
    explicit status flip, independent of Lesson.status — mirrors Quiz."""

    __tablename__ = "assignments"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_assignments_lesson_id", "lesson_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id = Column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    prompt = Column(Text, nullable=False)
    max_points = Column(Numeric(6, 2), nullable=False, default=100)
    due_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(
        SAEnum(AssignmentStatus, name="assignment_status"),
        default=AssignmentStatus.draft,
        nullable=False,
    )
    attachments_enabled = Column(Boolean, nullable=False, default=True)
    max_files = Column(Integer, nullable=False, default=5)
    # List[str] of lower-case extensions without the dot (subset of
    # ASSIGNMENT_ALLOWED_EXTENSIONS); validated on create/update.
    allowed_ext = Column(JSONB, nullable=False, default=list)
    max_file_mb = Column(Integer, nullable=False, default=10)
    # 0..1 normalized; null = no auto-completion on grade.
    pass_threshold = Column(Numeric(5, 4), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    lesson = relationship("Lesson", back_populates="assignments")
    submissions = relationship(
        "AssignmentSubmission",
        back_populates="assignment",
        cascade="all, delete-orphan",
    )


class AssignmentSubmission(Base):
    """One student's submission to one assignment. UNIQUE(enrollment, assignment)
    so a double-submit race collapses to a single row (caught as IntegrityError)."""

    __tablename__ = "assignment_submissions"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        UniqueConstraint(
            "enrollment_id", "assignment_id",
            name="uq_assignment_submissions_enrollment_assignment",
        ),
        Index("ix_assignment_submissions_assignment_id", "assignment_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assignment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assignments.id", ondelete="CASCADE"),
        nullable=False,
    )
    enrollment_id = Column(
        UUID(as_uuid=True),
        ForeignKey("enrollments.id", ondelete="CASCADE"),
        nullable=False,
    )
    text_content = Column(Text, nullable=True)
    status = Column(
        SAEnum(SubmissionStatus, name="submission_status"),
        default=SubmissionStatus.draft,
        nullable=False,
    )
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    # Normalized 0..1 for the gradebook; null until graded.
    score = Column(Numeric(5, 4), nullable=True)
    points_awarded = Column(Numeric(6, 2), nullable=True)
    feedback = Column(Text, nullable=True)
    graded_at = Column(DateTime(timezone=True), nullable=True)
    graded_by = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    assignment = relationship("Assignment", back_populates="submissions")
    enrollment = relationship("Enrollment")
    attachments = relationship(
        "AssignmentAttachment",
        back_populates="submission",
        cascade="all, delete-orphan",
    )
    messages = relationship(
        "AssignmentMessage",
        back_populates="submission",
        cascade="all, delete-orphan",
        order_by="AssignmentMessage.created_at",
    )


class AssignmentAttachment(Base):
    __tablename__ = "assignment_attachments"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_assignment_attachments_submission_id", "submission_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assignment_submissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    kind = Column(
        SAEnum(AttachmentKind, name="attachment_kind"),
        nullable=False,
        default=AttachmentKind.submission,
    )
    # Storage-relative path (e.g. "assignments/<submission_id>/<uuid>_essay.pdf").
    file_path = Column(String(512), nullable=False)
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(128), nullable=True)
    size_bytes = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    submission = relationship("AssignmentSubmission", back_populates="attachments")


class AssignmentMessage(Base):
    """A private thread message between the submitting student and the teacher."""

    __tablename__ = "assignment_messages"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (
        Index("ix_assignment_messages_submission_id", "submission_id"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    submission_id = Column(
        UUID(as_uuid=True),
        ForeignKey("assignment_submissions.id", ondelete="CASCADE"),
        nullable=False,
    )
    author_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    body = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    submission = relationship("AssignmentSubmission", back_populates="messages")
    author = relationship("User", lazy="joined")
