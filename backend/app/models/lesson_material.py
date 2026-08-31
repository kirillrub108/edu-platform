import uuid

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class LessonMaterial(Base):
    """A supplementary file a teacher attaches to a lesson's knowledge base.

    Files are only STORED, never parsed server-side (same contract as
    assignment attachments). No retention window — a material lives as long as
    its lesson; the stored object is removed on explicit delete or on hard
    purge of the lesson (see tasks/purge_pipeline).
    """

    __tablename__ = "lesson_materials"
    # See User.__mapper_args__: required for any model with onupdate=func.now()
    # (metadata PATCH returns the row right after UPDATE).
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (Index("ix_lesson_materials_lesson_created", "lesson_id", "created_at"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id = Column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    # Storage-relative path (e.g. "materials/<lesson_id>/<uuid>_handout.pdf").
    file_path = Column(String(512), nullable=False)
    original_filename = Column(String(255), nullable=False)
    content_type = Column(String(128), nullable=True)
    size_bytes = Column(Integer, nullable=False)
    # True for a file referenced from a text lesson's markdown body as
    # `material:{uuid}`. Same row, same storage/purge/delete path as a regular
    # material — the flag only splits the two UI lists apart and marks the rows
    # the body-save orphan sweep may reclaim.
    is_inline = Column(Boolean, nullable=False, default=False, server_default="false")
    uploaded_by = Column(
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

    lesson = relationship("Lesson", back_populates="materials")


class LessonNote(Base):
    """A teacher-authored markdown note in a lesson's knowledge base.

    Hand-written only — no LLM anywhere in this subsystem. `order` is a dense
    teacher-controlled sequence maintained by the reorder endpoint.
    """

    __tablename__ = "lesson_notes"
    __mapper_args__ = {"eager_defaults": True}
    __table_args__ = (Index("ix_lesson_notes_lesson_order", "lesson_id", "order"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    lesson_id = Column(
        UUID(as_uuid=True),
        ForeignKey("lessons.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    order = Column(Integer, default=0, nullable=False)
    created_by = Column(
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

    lesson = relationship("Lesson", back_populates="notes")
