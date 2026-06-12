import enum
import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class ContentType(str, enum.Enum):
    video = "video"
    text = "text"
    quiz = "quiz"


class LessonStatus(str, enum.Enum):
    draft = "draft"
    analyzing = "analyzing"
    ready_for_edit = "ready_for_edit"
    processing = "processing"
    published = "published"
    error = "error"
    cancelled = "cancelled"


class CreationMode(str, enum.Enum):
    presentation_and_text = "presentation_and_text"
    presentation_auto = "presentation_auto"
    text_only = "text_only"
    prompt = "prompt"
    video_upload = "video_upload"


class Module(Base):
    __tablename__ = "modules"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    course_id = Column(
        UUID(as_uuid=True), ForeignKey("courses.id", ondelete="CASCADE"), nullable=False
    )
    title = Column(String(255), nullable=False)
    order = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    course = relationship("Course", back_populates="modules")
    lessons = relationship(
        "Lesson",
        back_populates="module",
        cascade="all, delete-orphan",
        order_by="Lesson.order",
    )


class Lesson(Base):
    __tablename__ = "lessons"
    # See User.__mapper_args__ for rationale.
    __mapper_args__ = {"eager_defaults": True}

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    module_id = Column(
        UUID(as_uuid=True), ForeignKey("modules.id", ondelete="CASCADE"), nullable=False
    )
    title = Column(String(255), nullable=False)
    order = Column(Integer, default=0, nullable=False)
    content_type = Column(
        SAEnum(ContentType, name="content_type"),
        default=ContentType.video,
        nullable=False,
    )
    pptx_path = Column(String(512), nullable=True)
    video_url = Column(String(512), nullable=True)
    text_content = Column(Text, nullable=True)
    script = Column(Text, nullable=True)
    creation_mode = Column(
        SAEnum(CreationMode, name="creation_mode"),
        default=CreationMode.presentation_and_text,
        nullable=False,
    )
    status = Column(
        SAEnum(LessonStatus, name="lesson_status"),
        default=LessonStatus.draft,
        nullable=False,
    )
    analyze_task_id = Column(String(64), nullable=True)
    video_task_id = Column(String(64), nullable=True)
    last_warning = Column(Text, nullable=True)
    # Billing state of the active (or last) generation run. billing_ref is the
    # unique per-launch ledger key (RESERVE/finalizer rows in credit_transactions);
    # billed_via ('credits' | 'trial') is non-null only while a run is unsettled —
    # claiming it (set to NULL) is the idempotency guard between the task's
    # finalizer and the cancel endpoint. cancel_requested is the cooperative
    # cancellation flag polled by pipelines at per-slide checkpoints.
    credit_estimate = Column(Integer, nullable=True)
    credits_spent = Column(Integer, nullable=False, default=0, server_default="0")
    billing_ref = Column(String(64), nullable=True)
    billed_via = Column(String(16), nullable=True)
    cancel_requested = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Soft delete: non-null = hidden everywhere (see app/database.py global filter).
    deleted_at = Column(DateTime(timezone=True), nullable=True, default=None, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    module = relationship("Module", back_populates="lessons")
    quiz = relationship(
        "Quiz",
        back_populates="lesson",
        cascade="all, delete-orphan",
        uselist=False,
    )
    slide_texts = relationship(
        "SlideText",
        back_populates="lesson",
        cascade="all, delete-orphan",
        order_by="SlideText.slide_number",
    )
    videos = relationship(
        "LessonVideo",
        back_populates="lesson",
        cascade="all, delete-orphan",
    )
    assignments = relationship(
        "Assignment",
        back_populates="lesson",
        cascade="all, delete-orphan",
    )
